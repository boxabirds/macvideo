import { createBrowserRouter } from "react-router";
import SongBrowser from "./routes/SongBrowser";
import SongEditor from "./routes/SongEditor";

export const router = createBrowserRouter([
  {
    path: "/",
    element: (
      <div className="app">
        <div className="topbar"><h1>macvideo storyboard editor</h1></div>
        <SongBrowser />
      </div>
    ),
  },
  {
    path: "/songs/:slug",
    element: <SongEditor />,
  },
]);
