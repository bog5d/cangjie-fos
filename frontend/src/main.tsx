import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import App from "./App";
import "./index.css";

const ReviewWorkbench = lazy(() => import("./pages/ReviewWorkbench"));

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<App />} />
        <Route
          path="/review/:job_id"
          element={
            <Suspense
              fallback={
                <div className="flex h-screen items-center justify-center bg-[#0a0a14] text-slate-400 text-sm">
                  载入审查台…
                </div>
              }
            >
              <ReviewWorkbench />
            </Suspense>
          }
        />
      </Routes>
    </BrowserRouter>
  </React.StrictMode>,
);
