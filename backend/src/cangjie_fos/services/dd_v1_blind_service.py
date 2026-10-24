"""DD-V1 盲化服务（cangjie-fos#71 A4a · G-A4a-1 补料盲化）。

职责（全部确定性、零模型、零费用）：
1. ``blind_material``：把「材料目录内的相对路径 + 正文里的泄漏串」换成盲化名，产出
   ① 盲化材料目录 ② 新 ``meta.json``（``file_id`` 不变，只改 relative_path 与泄漏串）
   ③ 映射表（**必须**落在材料目录之外，由调用方用 ``mapping_out`` 指定）。
2. ``restore_material``：按映射表把盲化目录还原成原目录，**逐件 sha256 与原件一致**。
3. ``verify_blind``：盲化目录里 grep 不到泄漏词（题号 / 机构名 / 项目名）。

不变量：
- 盲化**只改泄漏串**，不改变材料本身的类型语义（meta 的 ``file_id`` / ``doc_type`` /
  ``entity`` / ``period`` 语义不变；只有字段里含泄漏串时才替换该串）。
- 盲化名**不以数字 + 分隔符开头** ⇒ 不会命中 ``dd_v1_doc_type_service.is_index_artifact``
  的索引件判定（形如「1_」「01-」「02.」的前缀）。
- 映射表**不得**落在材料目录内、不得落在盲化目录内（本服务强制 fail closed）。
"""
from __future__ import annotations

BLIND_IMPL_BEGIN = "GM:A4A:BLIND:IMPL:BEGIN"

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

BLIND_SCHEMA_VERSION = "dd_v1_blind.v1"
#: 盲化占位符（**不以数字开头** ⇒ 不会命中 dd_v1_doc_type_service.is_index_artifact 的 `^\d{1,2}[_\-.]`）
PLACEHOLDER_FMT = "BLIND-{idx:04d}"
DEFAULT_META_FILE = "meta.json"
#: 盲化时跳过的目录/文件（构建产物、版本库残留、隐藏文件）
SKIP_NAMES = {"__pycache__", ".git", ".DS_Store"}


class BlindError(RuntimeError):
    """盲化失败（fail closed：绝不产出半盲化的材料）。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def build_substitution_table(leak_words: Iterable[str]) -> dict[str, str]:
    """泄漏词 → 盲化占位符。

    确定性：按 (长度降序, 词) 排序后编号 ⇒ 同一份词表永远得到同一张映射表
    （拆分步与运行步各自盲化时口径一致）。
    """
    words = [w for w in dict.fromkeys(str(x) for x in leak_words) if w and str(w).strip()]
    if not words:
        raise BlindError("BLIND_NO_LEAK_WORDS")
    ordered = sorted(words, key=lambda w: (-len(w), w))
    return {w: PLACEHOLDER_FMT.format(idx=i + 1) for i, w in enumerate(ordered)}


def blind_text(text: str, table: dict[str, str]) -> str:
    """把文本里的泄漏串换成占位符（长词优先：短词不得先吃掉长词的一部分）。"""
    out = str(text)
    for word, ph in sorted(table.items(), key=lambda kv: (-len(kv[0]), kv[0])):
        out = out.replace(word, ph)
    return out


def restore_text(text: str, table: dict[str, str]) -> str:
    """把占位符换回泄漏串（盲化的逆运算）。"""
    out = str(text)
    for word, ph in sorted(table.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out = out.replace(ph, word)
    return out


def blind_relative_path(rel: str, table: dict[str, str]) -> str:
    """相对路径逐段盲化（目录名 + 文件名都在射程内）。"""
    parts = [p for p in PurePosixPath(str(rel).replace("\\", "/")).parts if p not in (".", "/")]
    return "/".join(blind_text(p, table) for p in parts)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    return _sha256_bytes(Path(path).read_bytes())


def _blind_bytes(data: bytes, table: dict[str, str]) -> bytes:
    """字节级替换（文本与二进制都安全）。"""
    out = data
    for word, ph in sorted(table.items(), key=lambda kv: (-len(kv[0]), kv[0])):
        out = out.replace(word.encode("utf-8"), ph.encode("utf-8"))
    return out


def _restore_bytes(data: bytes, table: dict[str, str]) -> bytes:
    out = data
    for word, ph in sorted(table.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        out = out.replace(ph.encode("utf-8"), word.encode("utf-8"))
    return out


def _assert_no_placeholder_collision(data: bytes, table: dict[str, str]) -> None:
    """原件里若已含占位符文本 ⇒ 还原不可逆 ⇒ fail closed。"""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return
    for ph in table.values():
        if ph in text:
            raise BlindError(f"BLIND_PLACEHOLDER_COLLISION:{ph}")


def _iter_material_files(src: Path, skip_rel: str) -> list[Path]:
    out: list[Path] = []
    for p in sorted(src.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(src).as_posix()
        if rel == skip_rel:
            continue
        if p.name.startswith("."):
            continue
        if any(part in SKIP_NAMES for part in p.relative_to(src).parts):
            continue
        out.append(p)
    return out


def blind_material(material_dir: Path, meta: list[dict[str, Any]], *, leak_words: Iterable[str],
                   blind_dir: Path, mapping_out: Path | None = None,
                   meta_file: Path | None = None) -> dict[str, Any]:
    """盲化材料目录，产出 ① 盲化目录 ② 新 meta.json ③ 映射表。

    - ``file_id`` **保持不变**；只改 ``relative_path`` 与字段里出现的泄漏串。
    - 映射表**必须**落在材料目录与盲化目录之外（否则 fail closed）。
    - 返回 ``{"blind_dir", "mapping", "meta", "files", "mapping_out"}``。
    """
    src = Path(material_dir).resolve()
    dst = Path(blind_dir).resolve()
    if not src.is_dir():
        raise BlindError(f"BLIND_SOURCE_NOT_DIR:{src}")
    if dst == src or src in dst.parents:
        raise BlindError(f"BLIND_DIR_INSIDE_SOURCE:{dst}")
    if dst in src.parents:
        raise BlindError(f"BLIND_DIR_CONTAINS_SOURCE:{dst}")
    table = build_substitution_table(leak_words)
    meta_path = Path(meta_file).resolve() if meta_file else (src / DEFAULT_META_FILE)
    try:
        meta_rel = meta_path.relative_to(src).as_posix()
    except ValueError:
        raise BlindError("BLIND_META_FILE_OUTSIDE_SOURCE")
    if not (src / meta_rel).is_file():
        raise BlindError(f"BLIND_META_FILE_MISSING:{meta_rel}")
    mapping_path = Path(mapping_out).resolve() if mapping_out else None
    if mapping_path is not None:
        for forbidden in (src, dst):
            if mapping_path == forbidden or forbidden in mapping_path.parents:
                raise BlindError(f"BLIND_MAPPING_INSIDE_MATERIAL:{mapping_path}")
    meta_index = {str(m.get("relative_path")): str(m.get("file_id")) for m in meta}
    for rel in meta_index:
        if not (src / rel).is_file():
            raise BlindError(f"BLIND_META_FILE_MISSING:{rel}")
    dst.mkdir(parents=True, exist_ok=True)
    file_entries: list[dict[str, Any]] = []
    for p in _iter_material_files(src, meta_rel):
        rel = p.relative_to(src).as_posix()
        data = p.read_bytes()
        _assert_no_placeholder_collision(data, table)
        blind_rel = blind_relative_path(rel, table)
        target = dst / blind_rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(_blind_bytes(data, table))
        file_entries.append({
            "file_id": meta_index.get(rel, ""),
            "original_relative_path": rel,
            "blind_relative_path": blind_rel,
            "sha256": _sha256_bytes(data),
        })
    new_meta: list[dict[str, Any]] = []
    for m in meta:
        entry: dict[str, Any] = {}
        for k, v in m.items():
            if k == "file_id":
                entry[k] = v
            elif k == "relative_path":
                entry[k] = blind_relative_path(str(v), table)
            elif isinstance(v, str):
                entry[k] = blind_text(v, table)
            else:
                entry[k] = v
        new_meta.append(entry)
    blind_meta_rel = blind_relative_path(meta_rel, table)
    (dst / blind_meta_rel).parent.mkdir(parents=True, exist_ok=True)
    (dst / blind_meta_rel).write_text(json.dumps(new_meta, ensure_ascii=False, indent=1), "utf-8")
    original_meta_bytes = (src / meta_rel).read_bytes()
    mapping = {
        "schema_version": BLIND_SCHEMA_VERSION,
        "created_at": _now_iso(),
        "source_dir": str(src),
        "blind_dir": str(dst),
        "leak_words": sorted(table),
        "substitutions": table,
        "meta": meta,
        "meta_file": {
            "original_relative_path": meta_rel,
            "blind_relative_path": blind_meta_rel,
            "original_text": original_meta_bytes.decode("utf-8"),
            "sha256": _sha256_bytes(original_meta_bytes),
        },
        "files": file_entries,
    }
    if mapping_path is not None:
        mapping_path.parent.mkdir(parents=True, exist_ok=True)
        mapping_path.write_text(json.dumps(mapping, ensure_ascii=False, indent=1), "utf-8")
    return {
        "blind_dir": str(dst),
        "mapping": mapping,
        "meta": new_meta,
        "files": file_entries,
        "mapping_out": str(mapping_path) if mapping_path else None,
    }


def restore_material(blind_dir: Path, mapping: Any, *, restore_dir: Path | None = None) -> Path:
    """按映射表还原盲化目录 → 原目录；**逐件 sha256 与原件一致**（不一致 ⇒ 抛错）。"""
    if isinstance(mapping, (str, Path)):
        mapping = json.loads(Path(mapping).read_text("utf-8"))
    table = dict(mapping.get("substitutions") or {})
    blind_root = Path(blind_dir).resolve()
    out = Path(restore_dir).resolve() if restore_dir else blind_root.with_name(blind_root.name + "_restored")
    if out == blind_root:
        raise BlindError("BLIND_RESTORE_TARGET_IS_BLIND_DIR")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for entry in mapping.get("files", []):
        src = blind_root / entry["blind_relative_path"]
        if not src.is_file():
            raise BlindError(f"BLIND_RESTORE_MISSING:{entry['blind_relative_path']}")
        data = _restore_bytes(src.read_bytes(), table)
        target = out / entry["original_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
        if _sha256_bytes(data) != entry["sha256"]:
            raise BlindError(f"BLIND_RESTORE_SHA_MISMATCH:{entry['original_relative_path']}")
    meta_file = mapping.get("meta_file") or {}
    if meta_file.get("original_relative_path"):
        target = out / meta_file["original_relative_path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(meta_file.get("original_text", ""), "utf-8")
        if meta_file.get("sha256") and _sha256_file(target) != meta_file["sha256"]:
            raise BlindError("BLIND_RESTORE_SHA_MISMATCH:meta.json")
    return out


def verify_blind(blind_dir: Path, leak_words: Iterable[str]) -> dict[str, Any]:
    """盲化目录里 grep 不到泄漏词（题号 / 机构名 / 项目名）。

    返回 ``{"ok", "hits", "checked_words"}``；``hits`` 同时覆盖**路径**与**正文**。
    """
    root = Path(blind_dir).resolve()
    words = [w for w in dict.fromkeys(str(x) for x in leak_words) if w and str(w).strip()]
    hits: list[dict[str, Any]] = []
    for p in sorted(root.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(root).as_posix()
        for w in words:
            if w in rel:
                hits.append({"kind": "PATH", "relative_path": rel, "word": w})
        try:
            text = p.read_bytes().decode("utf-8")
        except UnicodeDecodeError:
            continue
        for w in words:
            if w in text:
                hits.append({"kind": "CONTENT", "relative_path": rel, "word": w})
    return {"ok": not hits, "hits": hits, "checked_words": sorted(words)}
BLIND_IMPL_END = "GM:A4A:BLIND:IMPL:END"
