import "@/App.css";
import { BrowserRouter, Routes, Route, Navigate } from "react-router-dom";
import { Toaster } from "sonner";
import Layout from "@/components/Layout";
import Overview from "@/pages/Overview";
import CommandsPage from "@/pages/CommandsPage";
import ConfigPage from "@/pages/ConfigPage";
import AuditPage from "@/pages/AuditPage";
import ObfuscatorPage from "@/pages/ObfuscatorPage";
import ScriptsPage from "@/pages/ScriptsPage";
import KeysPage from "@/pages/KeysPage";
import LoadersPage from "@/pages/LoadersPage";

function App() {
  return (
    <div className="App">
      <BrowserRouter>
        <Routes>
          <Route element={<Layout />}>
            <Route path="/" element={<Overview />} />
            <Route path="/commands" element={<CommandsPage />} />
            <Route path="/obfuscate" element={<ObfuscatorPage />} />
            <Route path="/scripts" element={<ScriptsPage />} />
            <Route path="/loaders" element={<LoadersPage />} />
            <Route path="/keys" element={<KeysPage />} />
            <Route path="/config" element={<ConfigPage />} />
            <Route path="/audit" element={<AuditPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
      <Toaster
        position="bottom-right"
        theme="dark"
        toastOptions={{
          style: {
            background: "#0A0A0A",
            border: "1px solid rgba(255,255,255,0.12)",
            borderRadius: "2px",
            color: "#fff",
            fontFamily: "Inter, sans-serif",
          },
        }}
      />
    </div>
  );
}

export default App;
