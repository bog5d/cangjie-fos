# 扫描件 OCR 配置说明（v1.18.0）

尽调台读"扫描件 / 图片型 PDF"时会走 OCR（视觉模型），把图片识别成文字再匹配。
**默认开箱即用**，多数情况无需任何配置。

## 默认行为（推荐，零配置）

只要环境里配了 ASR 用的 `DASHSCOPE_API_KEY`（同事服务器一般早已配好），
扫描件 OCR 自动启用，模型用阿里百炼 `qwen-vl-max`，走百炼 OpenAI 兼容端点。

> OCR 只对「匹配出来的少数候选文件」里「读不出文字层的扫描件」触发，
> 不会对全库跑，成本可控。

## 想关掉（省 API 成本）

```env
CANGJIE_OCR_DISABLED=1
```

关掉后扫描件读不出字时退回文件名匹配（不报错，标记 readable=False）。

## 换模型 / 换供应商

```env
# 只换百炼模型（更便宜的）
CANGJIE_VISION_MODEL=qwen-vl-plus

# 或完全自定义视觉模型（任意 OpenAI 兼容端点，优先级最高）
CANGJIE_VISION_BASE_URL=https://your-endpoint/v1
CANGJIE_VISION_API_KEY=sk-xxx
CANGJIE_VISION_MODEL=your-vl-model
```

## 加密文件

加密的 Office/PDF 在尽调台界面**登记密码**后，精判时自动解密读取正文
（Office→msoffcrypto，PDF→pikepdf），无需环境变量配置。
