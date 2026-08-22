import "./style.css";
import { addRoute, setNotFoundHandler, startRouter } from "./router/router.ts";
import { renderHomePage } from "./pages/home.ts";
import { renderSessionDetailPage } from "./pages/sessionDetail.ts";
import { renderSearchPage } from "./pages/search.ts";
import { renderNotFoundPage } from "./pages/notFound.ts";

addRoute("/", renderHomePage);
addRoute("/sessions/:id", renderSessionDetailPage);
addRoute("/search", renderSearchPage);
setNotFoundHandler(renderNotFoundPage);

startRouter();
