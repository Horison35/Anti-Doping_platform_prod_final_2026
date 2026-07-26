import { useState } from "react"
import { Route, Routes } from "react-router-dom"
import { useAuthStatus } from "./api/hooks"
import { PasswordGate } from "./components/layout/PasswordGate"
import { Splash } from "./components/layout/Splash"
import { AppShell } from "./components/layout/AppShell"
import Overview from "./pages/Overview"
import Analytics from "./pages/Analytics"
import History from "./pages/History"
import Monitor from "./pages/Monitor"
import Exports from "./pages/Exports"
import Transparency from "./pages/Transparency"
import Help from "./pages/Help"

const SPLASH_KEY = "adp_splash_seen"

export default function App() {
  const authStatus = useAuthStatus()
  const [splashDone, setSplashDone] = useState(() => sessionStorage.getItem(SPLASH_KEY) === "1")

  if (authStatus.isLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-[var(--color-sub)]">
        Загрузка…
      </div>
    )
  }

  if (!authStatus.data?.authenticated) {
    return <PasswordGate />
  }

  if (!splashDone) {
    return (
      <Splash
        onContinue={() => {
          sessionStorage.setItem(SPLASH_KEY, "1")
          setSplashDone(true)
        }}
      />
    )
  }

  return (
    <Routes>
      <Route element={<AppShell />}>
        <Route path="/" element={<Overview />} />
        <Route path="/analytics" element={<Analytics />} />
        <Route path="/history" element={<History />} />
        <Route path="/monitor" element={<Monitor />} />
        <Route path="/export" element={<Exports />} />
        <Route path="/о-системе" element={<Transparency />} />
        <Route path="/справка" element={<Help />} />
        <Route path="*" element={<Overview />} />
      </Route>
    </Routes>
  )
}
