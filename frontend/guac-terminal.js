(() => {
  "use strict";
  const status = document.getElementById("status");
  const screen = document.getElementById("screen");
  const params = new URLSearchParams(location.hash.slice(1));
  const token = params.get("token");
  const id = params.get("id");
  const source = params.get("source");
  if (!token || !id || !source || !window.Guacamole) {
    status.textContent = "The terminal could not start. Reconnect from your lab workspace.";
    throw new Error("Missing Guacamole connection data");
  }

  const tunnel = new Guacamole.WebSocketTunnel("/console/websocket-tunnel");
  const client = new Guacamole.Client(tunnel);
  const display = client.getDisplay().getElement();
  screen.appendChild(display);
  display.addEventListener("mousedown", () => screen.focus());

  const keyboard = new Guacamole.Keyboard(screen);
  keyboard.onkeydown = keysym => client.sendKeyEvent(1, keysym);
  keyboard.onkeyup = keysym => client.sendKeyEvent(0, keysym);
  const mouse = new Guacamole.Mouse(display);
  mouse.onmousedown = mouse.onmouseup = mouse.onmousemove = state => client.sendMouseState(state);

  function fit() {
    const remote = client.getDisplay();
    const width = remote.getWidth(), height = remote.getHeight();
    if (!width || !height) return;
    remote.scale(Math.min(screen.clientWidth / width, screen.clientHeight / height));
    client.sendSize(screen.clientWidth, screen.clientHeight);
  }
  tunnel.onerror = () => { status.textContent = "Terminal connection failed. Select Reconnect in your lab workspace."; };
  tunnel.onstatechange = state => {
    if (state === Guacamole.Tunnel.State.CLOSED) {
      status.textContent = "Terminal disconnected. Select Reconnect in your lab workspace.";
    }
  };
  client.onerror = () => { status.textContent = "Terminal connection failed. Select Reconnect in your lab workspace."; };
  client.onstatechange = state => {
    if (state === Guacamole.Client.State.CONNECTED) {
      status.textContent = "Connected. Click the terminal screen to type.";
      screen.focus();
      fit();
    } else if (state === Guacamole.Client.State.DISCONNECTED) {
      status.textContent = "Terminal disconnected. Select Reconnect in your lab workspace.";
    }
  };
  new ResizeObserver(fit).observe(screen);
  addEventListener("beforeunload", () => client.disconnect(), { once: true });
  const query = new URLSearchParams({ token, GUAC_ID: id, GUAC_DATA_SOURCE: source,
    GUAC_TYPE: "c", GUAC_WIDTH: String(screen.clientWidth),
    GUAC_HEIGHT: String(screen.clientHeight), GUAC_DPI: "96" });
  client.connect(query.toString());
})();
