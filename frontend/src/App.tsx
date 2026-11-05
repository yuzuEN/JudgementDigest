import { Navigate, Route, Routes } from "react-router-dom";
import CivilResult from "./pages/CivilResult";
import Confirm from "./pages/Confirm";
import CriminalResult from "./pages/CriminalResult";
import Home from "./pages/Home";
import Intake from "./pages/Intake";
import Reading from "./pages/Reading";

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Home />} />
      <Route path="/start" element={<Intake />} />
      <Route path="/confirm" element={<Confirm />} />
      <Route path="/result/civil" element={<CivilResult />} />
      <Route path="/result/criminal" element={<CriminalResult />} />
      <Route path="/judgment/:source/:caseId" element={<Reading />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
