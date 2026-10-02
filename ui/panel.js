// The panel only renders what Python sends and reports slider changes and questions back.

const SUITS = { s: "♠", h: "♥", d: "♦", c: "♣" };
const KINDS = { FOLD: "fold", CHECK: "passive", CALL: "passive", RAISE: "raise", "ALL-IN": "allin" };

function $(id) { return document.getElementById(id); }

function send(message) {
  if (window.webkit && window.webkit.messageHandlers.bridge) {
    window.webkit.messageHandlers.bridge.postMessage(message);
  }
}

function cardTile(card) {
  const tile = document.createElement("div");
  tile.className = "card" + (card[1] === "h" || card[1] === "d" ? " red" : "");
  const rank = document.createElement("span");
  rank.textContent = card[0] === "T" ? "10" : card[0];
  const suit = document.createElement("span");
  suit.className = "suit";
  suit.textContent = SUITS[card[1]] || "";
  tile.append(rank, suit);
  return tile;
}

function renderCards(id, cards, slots) {
  const box = $(id);
  box.replaceChildren();
  (cards || []).forEach(card => box.append(cardTile(card)));
  for (let i = (cards || []).length; i < slots; i++) {
    const empty = document.createElement("div");
    empty.className = "card none";
    box.append(empty);
  }
}

function percent(value) {
  return value === null || value === undefined ? "-" : Math.round(value * 100) + " %";
}

function text(value) {
  return value === null || value === undefined || value === "" ? "-" : String(value);
}

function renderDecision(m) {
  const decision = $("decision");
  if (!m.action) {
    decision.className = "wait";
    $("action").textContent = m.headline || "Warte auf den Tisch";
    $("source").textContent = "";
    $("clamp-note").textContent = "";
    return;
  }
  decision.className = KINDS[m.action] || "wait";
  $("action").textContent = m.action + (m.amount ? " " + m.amount : "");
  $("source").textContent = m.source || "";
  $("clamp-note").textContent = m.clamp_note || "";
}

function renderEquity(m) {
  $("equity").textContent = percent(m.equity);
  $("required").textContent = m.to_call ? percent(m.required) : "-";
  const fill = $("equity-fill");
  fill.style.width = m.equity === null || m.equity === undefined ? "0" : Math.round(m.equity * 100) + "%";
  const mark = $("required-mark");
  const hasMark = m.to_call && m.required !== null && m.required !== undefined;
  mark.style.display = hasMark ? "block" : "none";
  if (hasMark) mark.style.left = Math.round(m.required * 100) + "%";
  fill.className = hasMark && m.equity !== null && m.equity < m.required ? "short" : "";
  $("equity-basis").textContent = m.opponents_n
    ? "gegen " + m.opponents_n + (m.opponents_n === 1 ? " Zufallshand" : " Zufallshände")
    : "gegen Zufallshände";
}

function renderOpponents(list) {
  const box = $("opponents");
  box.replaceChildren();
  if (!list || !list.length) {
    const empty = document.createElement("li");
    empty.className = "empty";
    empty.textContent = "Noch niemand beobachtet.";
    box.append(empty);
    return;
  }
  list.forEach(o => {
    const row = document.createElement("li");
    if (!o.in_hand) row.className = "out";
    const name = document.createElement("span");
    name.textContent = o.name;
    const detail = document.createElement("span");
    detail.className = "detail";
    detail.textContent = o.label + (o.counts ? ", " + o.counts : "") + (o.hands ? " (" + o.hands + (o.hands === 1 ? " Hand)" : " Hände)") : "");
    row.append(name, detail);
    box.append(row);
  });
}

function renderTranscript(lines) {
  const box = $("transcript");
  const stick = box.scrollTop + box.clientHeight >= box.scrollHeight - 8;
  box.replaceChildren();
  (lines || []).forEach(line => {
    const item = document.createElement("li");
    item.className = line.who;
    item.textContent = line.text;
    box.append(item);
  });
  if (stick) box.scrollTop = box.scrollHeight;
}

function renderStrategy(s) {
  if (!s) return;
  $("strategy-name").textContent = s.name || "";
  ["tightness", "aggression", "bluff"].forEach(key => {
    if (document.activeElement !== $(key)) $(key).value = s[key];
    $(key + "-value").textContent = $(key).value;
  });
}

// called from Python with the full view model
function update(m) {
  renderDecision(m);
  renderCards("hand", m.hand, 2);
  renderCards("board", m.board, 5);
  $("street").textContent = m.street || "";
  renderEquity(m);
  $("pot").textContent = text(m.pot);
  $("to-call").textContent = text(m.to_call);
  $("position").textContent = text(m.position);
  $("opponents-n").textContent = text(m.opponents_n);
  const why = $("why");
  why.textContent = m.why || "Noch keine Empfehlung.";
  why.className = m.why ? "" : "empty";
  renderOpponents(m.opponents);
  renderTranscript(m.transcript);
  renderStrategy(m.strategy);
  $("status").textContent = m.status || "";
  $("backend").textContent = m.backend || "";
}

["tightness", "aggression", "bluff"].forEach(key => {
  $(key).addEventListener("input", () => { $(key + "-value").textContent = $(key).value; });
  $(key).addEventListener("change", () => send({
    type: "strategy",
    tightness: Number($("tightness").value),
    aggression: Number($("aggression").value),
    bluff: Number($("bluff").value),
  }));
});

$("think").addEventListener("click", () => send({ type: "think" }));

$("ask-form").addEventListener("submit", event => {
  event.preventDefault();
  const question = $("ask").value.trim();
  if (!question) return;
  $("ask").value = "";
  send({ type: "ask", text: question });
});

send({ type: "ready" });
