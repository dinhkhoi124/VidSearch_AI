// src/App.jsx

import SearchPage from "./pages/SearchPage";
import './App.css';

function App() {
  // Bỏ đi các class giới hạn chiều rộng, để SearchPage tự quản lý layout
  return <SearchPage />;
}

export default App;