// KANTOOR 3D: het Sideways Wire-terrein. Vier garages rond een driftpad, met de agents als poppetjes.
// Gegevens: docs/agents/<id>.json + data/agents.json (via loadAgents in index.html) en status.json (posts).
// Alles is zelf opgebouwd uit simpele vormen (geen modellen van anderen), in de kleuren van Sideways Wire.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "./vendor/three/CSS2DRenderer.js";

const LIME = 0xC6FF00, PINK = 0xFF2E88, BLUE = 0x5BC0FF, ORANGE = 0xFF9F43, DARK = 0x151517;
const STC = { bezig: "#C6FF00", wacht: "#9a9aa0", pauze: "#ffb000", uit: "#555", fout: "#FF2E88", gepland: "#5BC0FF" };

// ---------- wie werkt waar ----------
const GARAGES = [
  { id: "directie", name: "DIRECTIE", sub: "plan en richting", x: -21, w: 11, color: BLUE },
  { id: "redactie", name: "REDACTIE", sub: "clips en nieuws", x: -6, w: 15, color: LIME },
  { id: "pitwall", name: "PITWALL", sub: "controle en cijfers", x: 10.5, w: 13, color: PINK },
  { id: "jij", name: "JOUW GARAGE", sub: "akkoord en systeem", x: 24.5, w: 11, color: ORANGE },
];
const DEPTH = 9, WALL_H = 4.2;
// look: [shirt, broek, huid, pet/haar, extra]  extra: cap | beanie | headset | hair
const AGENTS = {
  strateeg:       { g: "directie", at: [-3, -2.5], role: "Strateeg", look: [0x5BC0FF, 0x22252c, 0xe8b48a, 0x1d1d1d, "hair"] },
  hoofdredacteur: { g: "directie", at: [1.8, -2.5], role: "Hoofdredacteur", look: [0xf2f2f2, 0x1a1a1a, 0xc98a5e, 0x8a8a8a, "hair"] },
  battle:         { g: "redactie", at: [-5, 1.2], role: "Battle-redacteur", look: [0xFF2E88, 0x1d1d22, 0xf1c19a, 0x111111, "cap"] },
  podcast:        { g: "redactie", at: [-1.6, 1.2], role: "Podcast-redacteur", look: [0xC6FF00, 0x2b2b30, 0x8d5a3b, 0x222222, "headset"] },
  nieuws:         { g: "redactie", at: [1.8, 1.2], role: "Nieuwsredacteur", look: [0xFF9F43, 0x24242a, 0xf3cfae, 0xe0c060, "hair"] },
  community:      { g: "redactie", at: [5.2, 1.2], role: "Community", look: [0xb388ff, 0x202026, 0xc68e6a, 0x3a2a5a, "beanie"] },
  qc:             { g: "pitwall", at: [-4.2, -1.2], role: "Kwaliteitscontrole", look: [0xffffff, 0x1d1d1d, 0xe2a77f, 0xFF2E88, "cap"] },
  scout:          { g: "pitwall", at: [-1.4, -1.2], role: "Nieuwsscout", look: [0x2ecc71, 0x232323, 0xf0c8a0, 0xb5651d, "beanie"] },
  analist:        { g: "pitwall", at: [1.4, -1.2], role: "Analist", look: [0x5BC0FF, 0x1d1d22, 0xd9a27a, 0x444444, "hair"] },
  tags:           { g: "pitwall", at: [4.2, -1.2], role: "Tagsonderzoeker", look: [0xFF9F43, 0x24242a, 0xeac0a0, 0x6b4226, "cap"] },
  wachter:        { g: "jij", at: [3.2, -2.2], role: "Systeemwachter", look: [0x3a3a40, 0x161616, 0xa8704c, 0xC6FF00, "beanie"], stand: true },
};

let renderer, labelR, scene, camera, controls, clock, box, ready = false, raf = 0;
const agentObj = {}, clickables = [], blinkers = [], screens = {}, fx = { smoke: [], car: null, t: 0, lights: [] };
let camGoal = null, pick = null, boards = {};

// ---------- helpers ----------
const mat = (c, o = {}) => new THREE.MeshStandardMaterial({ color: c, roughness: o.r ?? .7, metalness: o.m ?? .05, emissive: o.e ?? 0, emissiveIntensity: o.ei ?? 1, ...(o.extra || {}) });
function mesh(geo, m, x = 0, y = 0, z = 0, parent) {
  const o = new THREE.Mesh(geo, m); o.position.set(x, y, z); o.castShadow = true; o.receiveShadow = true;
  if (parent) parent.add(o); return o;
}
const B = (w, h, d) => new THREE.BoxGeometry(w, h, d);
function canvasTex(w, h, draw) {
  const c = document.createElement("canvas"); c.width = w; c.height = h; const g = c.getContext("2d"); draw(g, w, h);
  const t = new THREE.CanvasTexture(c); t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 4; t._c = c; t._draw = draw; return t;
}
function redraw(t, draw) { const g = t._c.getContext("2d"); g.clearRect(0, 0, t._c.width, t._c.height); draw(g, t._c.width, t._c.height); t.needsUpdate = true; }
function label(html, cls, parent, y) {
  const d = document.createElement("div"); d.className = cls; d.innerHTML = html;
  const o = new CSS2DObject(d); o.position.set(0, y, 0); parent.add(o); return o;
}
const hourNL = () => +new Date().toLocaleString("en-GB", { timeZone: "Europe/Amsterdam", hour: "2-digit", hour12: false });

// ---------- textures ----------
function concreteTex() {
  return canvasTex(512, 512, (g, w, h) => {
    g.fillStyle = "#4a4d52"; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 4000; i++) { g.fillStyle = `rgba(${Math.random() < .5 ? 0 : 255},${Math.random() < .5 ? 0 : 255},${Math.random() < .5 ? 0 : 255},.035)`; g.fillRect(Math.random() * w, Math.random() * h, 2, 2); }
    for (let i = 0; i < 9; i++) { const x = Math.random() * w, y = Math.random() * h, r = 20 + Math.random() * 50;
      const gr = g.createRadialGradient(x, y, 2, x, y, r); gr.addColorStop(0, "rgba(10,10,12,.55)"); gr.addColorStop(1, "rgba(10,10,12,0)"); g.fillStyle = gr; g.beginPath(); g.arc(x, y, r, 0, 7); g.fill(); }
    g.strokeStyle = "rgba(0,0,0,.25)"; g.lineWidth = 2; for (let i = 128; i < w; i += 128) { g.beginPath(); g.moveTo(i, 0); g.lineTo(i, h); g.stroke(); g.beginPath(); g.moveTo(0, i); g.lineTo(w, i); g.stroke(); }
  });
}
function asphaltTex() {
  const t = canvasTex(1024, 1024, (g, w, h) => {
    g.fillStyle = "#26272b"; g.fillRect(0, 0, w, h);
    for (let i = 0; i < 20000; i++) { const v = 30 + Math.random() * 40 | 0; g.fillStyle = `rgba(${v},${v},${v + 4},.5)`; g.fillRect(Math.random() * w, Math.random() * h, 1.5, 1.5); }
    // bandensporen: donuts en lange drifts
    g.lineCap = "round";
    for (let k = 0; k < 7; k++) { const cx = 512 + (Math.random() - .5) * 260, cy = 640 + (Math.random() - .5) * 140, r = 90 + Math.random() * 120;
      for (const off of [-9, 9]) { g.strokeStyle = `rgba(5,5,6,${.25 + Math.random() * .35})`; g.lineWidth = 7 + Math.random() * 4; g.beginPath(); g.arc(cx, cy, r + off, Math.random() * 6, Math.random() * 6 + 3 + Math.random() * 3); g.stroke(); } }
    for (let k = 0; k < 5; k++) { g.strokeStyle = "rgba(5,5,6,.35)"; g.lineWidth = 8; const y = 820 + k * 30; g.beginPath(); g.moveTo(80, y); g.bezierCurveTo(350, y - 120, 650, y + 120, 950, y - 40); g.stroke(); }
    // lijnen van het startvak
    g.strokeStyle = "rgba(198,255,0,.55)"; g.lineWidth = 6; g.setLineDash([30, 22]); g.beginPath(); g.arc(512, 660, 300, 0, 7); g.stroke(); g.setLineDash([]);
  });
  return t;
}
function wallTex(accent) {
  return canvasTex(512, 256, (g, w, h) => {
    g.fillStyle = "#2a2b30"; g.fillRect(0, 0, w, h);
    for (let x = 0; x < w; x += 16) { g.fillStyle = x % 32 ? "#2f3036" : "#25262b"; g.fillRect(x, 0, 16, h); }
    g.fillStyle = "#" + accent.toString(16).padStart(6, "0"); g.fillRect(0, h - 26, w, 8);
    g.fillStyle = "#111"; g.fillRect(0, h - 18, w, 18);
    for (let x = 0; x < w; x += 40) { g.fillStyle = "#e8e8e8"; g.fillRect(x, h - 18, 20, 18); }
  });
}

// ---------- props ----------
function makeCar(color, parent, x, y, z, ry = 0, scale = 1) {
  const car = new THREE.Group(); car.position.set(x, y, z); car.rotation.y = ry; car.scale.setScalar(scale);
  const paint = mat(color, { r: .25, m: .6 }), black = mat(0x0c0c0e, { r: .5 }), glass = mat(0x101820, { r: .1, m: .8 });
  mesh(B(1.9, .45, 4.2), paint, 0, .55, 0, car);                       // onderkant
  mesh(B(1.95, .2, 4.0), black, 0, .33, 0, car);                       // sideskirts
  const cab = mesh(B(1.6, .5, 2.0), glass, 0, 1.0, -.2, car); cab.scale.x = .95;
  mesh(B(1.62, .08, 1.7), paint, 0, 1.28, -.25, car);                  // dak
  mesh(B(1.9, .06, .5), black, 0, 1.25, -2.05, car);                    // spoiler
  mesh(B(.08, .4, .08), black, -.7, 1.0, -1.95, car); mesh(B(.08, .4, .08), black, .7, 1.0, -1.95, car);
  mesh(B(1.7, .12, .1), mat(0xffffff, { e: 0xffffff, ei: 1.5 }), 0, .62, 2.11, car);   // koplampen
  mesh(B(1.7, .1, .1), mat(0xff0030, { e: 0xff0030, ei: 1.2 }), 0, .7, -2.11, car);   // achterlichten
  mesh(B(1.0, .25, .05), mat(LIME, { e: LIME, ei: .4 }), 0, .6, 2.12, car);            // nummerplaat in merkkleur
  // livery-streep
  mesh(B(1.96, .12, 4.0), mat(LIME, { e: LIME, ei: .25 }), 0, .68, 0, car);
  const wg = new THREE.CylinderGeometry(.38, .38, .32, 18); wg.rotateZ(Math.PI / 2);
  const rimG = new THREE.CylinderGeometry(.22, .22, .34, 10); rimG.rotateZ(Math.PI / 2);
  car.userData.wheels = [];
  for (const [wx, wz] of [[-.95, 1.35], [.95, 1.35], [-.95, -1.35], [.95, -1.35]]) {
    const wgp = new THREE.Group(); wgp.position.set(wx, .38, wz); car.add(wgp);
    mesh(wg, black, 0, 0, 0, wgp); mesh(rimG, mat(0xbfc3c8, { m: .9, r: .3 }), 0, 0, 0, wgp); car.userData.wheels.push(wgp);
  }
  parent.add(car); return car;
}
function tireStack(parent, x, z, n = 4, stripe) {
  const g = new THREE.TorusGeometry(.38, .17, 8, 18); g.rotateX(Math.PI / 2);
  for (let i = 0; i < n; i++) mesh(g, mat(i === n - 1 && stripe ? stripe : 0x111113, { r: .9 }), x, .17 + i * .32, z, parent);
}
function desk(parent, x, z, id, accent) {
  const gp = new THREE.Group(); gp.position.set(x, 0, z); gp.rotation.y = Math.PI; parent.add(gp);
  const top = mat(0x1d1e22, { r: .4 }), leg = mat(0x0f0f11);
  mesh(B(2.2, .08, 1.0), top, 0, .9, 0, gp); mesh(B(2.2, .04, 1.0), mat(accent, { e: accent, ei: .15 }), 0, .85, 0, gp);
  for (const [lx, lz] of [[-1, -.4], [1, -.4], [-1, .4], [1, .4]]) mesh(B(.06, .86, .06), leg, lx, .43, lz, gp);
  // twee schermen
  const scrM = mat(0x050507, { e: 0x1a2a33, ei: 1 });
  for (const sx of [-.42, .42]) { mesh(B(.8, .5, .05), mat(0x0b0b0d), sx, 1.32, -.3, gp); const s = mesh(B(.74, .44, .02), scrM, sx, 1.32, -.27, gp); s.castShadow = false;
    mesh(B(.05, .3, .05), leg, sx, 1.05, -.32, gp); const bk = mesh(B(.5, .07, .01), scrM, sx, 1.45, -.33, gp); bk.castShadow = false; }
  screens[id] = scrM;
  mesh(B(.7, .03, .22), mat(0x2a2a2e), 0, .95, .15, gp);                // toetsenbord
  mesh(B(.3, .3, .3), mat(0x2a2a2e), .85, 1.1, .2, gp).scale.set(.4, .5, .4);  // blikje
  // stoel
  const ch = new THREE.Group(); ch.position.set(0, 0, .95); gp.add(ch);
  mesh(B(.7, .1, .65), mat(0x111114), 0, .55, 0, ch); mesh(B(.7, .85, .1), mat(0x111114), 0, 1.0, .32, ch);
  mesh(B(.72, .12, .12), mat(accent, { e: accent, ei: .3 }), 0, 1.35, .32, ch);
  mesh(new THREE.CylinderGeometry(.05, .05, .5, 6), leg, 0, .27, 0, ch);
  return gp;
}
function person(parent, look, x, z, id, seated) {
  const [shirt, pants, skin, hairC, extra] = look;
  const p = new THREE.Group(); p.position.set(x, 0, z); parent.add(p);
  const body = new THREE.Group(); p.add(body);
  const sh = mat(shirt, { r: .8 }), pa = mat(pants), sk = mat(skin, { r: .6 }), hc = mat(hairC);
  const legY = seated ? .55 : 0;
  if (seated) { mesh(B(.22, .2, .6), pa, -.13, .6, -.15, body); mesh(B(.22, .2, .6), pa, .13, .6, -.15, body); mesh(B(.2, .55, .2), pa, -.13, .3, -.42, body); mesh(B(.2, .55, .2), pa, .13, .3, -.42, body); }
  else { mesh(B(.22, .8, .22), pa, -.13, .4, 0, body); mesh(B(.22, .8, .22), pa, .13, .4, 0, body); }
  const torso = mesh(new THREE.CapsuleGeometry(.27, .45, 4, 10), sh, 0, legY + .62 + (seated ? .05 : .25), 0, body);
  // logo op de rug: limestreep
  mesh(B(.3, .06, .02), mat(LIME, { e: LIME, ei: .3 }), 0, torso.position.y + .1, .27, body);
  const head = new THREE.Group(); head.position.set(0, torso.position.y + .58, 0); body.add(head);
  mesh(new THREE.SphereGeometry(.24, 16, 12), sk, 0, 0, 0, head);
  mesh(B(.05, .05, .02), mat(0x111111), -.08, .03, -.23, head); mesh(B(.05, .05, .02), mat(0x111111), .08, .03, -.23, head);
  if (extra === "cap") { mesh(new THREE.SphereGeometry(.25, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), hc, 0, .06, 0, head); mesh(B(.3, .03, .2), hc, 0, .08, -.25, head); }
  else if (extra === "beanie") { mesh(new THREE.SphereGeometry(.26, 14, 8, 0, Math.PI * 2, 0, Math.PI / 1.9), hc, 0, .04, 0, head); mesh(new THREE.SphereGeometry(.06, 8, 6), hc, 0, .3, 0, head); }
  else { mesh(new THREE.SphereGeometry(.25, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2.2), hc, 0, .05, .02, head); }
  if (extra === "headset") { mesh(new THREE.TorusGeometry(.26, .03, 6, 16, Math.PI), mat(0x111111), 0, .04, 0, head); mesh(B(.08, .14, .1), mat(LIME, { e: LIME, ei: .4 }), -.26, 0, 0, head); mesh(B(.08, .14, .1), mat(LIME, { e: LIME, ei: .4 }), .26, 0, 0, head); }
  const arms = [];
  for (const s of [-1, 1]) { const a = new THREE.Group(); a.position.set(s * .33, torso.position.y + .25, 0); body.add(a);
    mesh(B(.15, .5, .15), sh, 0, -.22, 0, a); mesh(B(.13, .13, .13), sk, 0, -.5, 0, a); a.rotation.x = seated ? 1.1 : 0; arms.push(a); }
  p.userData = { id, body, head, arms, seated, baseY: 0 };
  p.traverse(o => { if (o.isMesh) { o.userData.agent = id; clickables.push(o); } });
  return p;
}
function neonText(text, color, w = 6, h = 1) {
  return canvasTex(1024, Math.round(1024 * h / w), (g, W, H) => {
    g.clearRect(0, 0, W, H); g.font = `italic 900 ${H * .62}px "Bebas Neue", Impact, sans-serif`; g.textAlign = "center"; g.textBaseline = "middle";
    g.shadowColor = color; g.shadowBlur = 30; g.fillStyle = color; g.fillText(text, W / 2, H / 2); g.shadowBlur = 0; g.fillStyle = "#fff"; g.globalAlpha = .55; g.fillText(text, W / 2, H / 2);
  });
}
function plane(tex, w, h, parent, x, y, z, ry = 0, glow = 1) {
  const m = new THREE.MeshBasicMaterial({ map: tex, transparent: true, toneMapped: false });
  m.color.multiplyScalar(glow);
  const o = new THREE.Mesh(new THREE.PlaneGeometry(w, h), m); o.position.set(x, y, z); o.rotation.y = ry; parent.add(o); return o;
}

// ---------- garages ----------
function garage(G) {
  const g = new THREE.Group(); g.position.set(G.x, 0, -6); scene.add(g); G.group = g;
  const W = G.w, D = DEPTH, wt = wallTex(G.color);
  const conc = concreteTex(); conc.wrapS = conc.wrapT = THREE.RepeatWrapping; conc.repeat.set(W / 6, D / 6);
  mesh(B(W, .2, D), mat(0xffffff, { r: .85, extra: { map: conc } }), 0, -.1, 0, g).castShadow = false;
  const wm = mat(0xffffff, { r: .8, extra: { map: wt } });
  const back = mesh(B(W, WALL_H, .25), wm, 0, WALL_H / 2, -D / 2, g);
  mesh(B(.25, WALL_H, D), wm, -W / 2, WALL_H / 2, 0, g); mesh(B(.25, WALL_H, D), wm, W / 2, WALL_H / 2, 0, g);
  // stalen frame en open dak met spanten
  const steel = mat(0x1a1b1f, { m: .6, r: .4 });
  for (const sx of [-W / 2, W / 2]) mesh(B(.35, WALL_H + .6, .35), steel, sx, (WALL_H + .6) / 2, D / 2, g);
  const lintel = mesh(B(W + .35, .3, .4), mat(G.color, { e: G.color, ei: .2, r: .5 }), 0, WALL_H + .45, D / 2, g);
  for (let i = -1; i <= 1; i++) mesh(B(.12, .12, D), steel, i * W / 3, WALL_H + .1, 0, g);
  // naambord boven de deur
  const sign = canvasTex(1024, 128, (c, w, h) => { c.fillStyle = "#111"; c.fillRect(0, 0, w, h); c.font = `italic 900 84px "Bebas Neue",Impact,sans-serif`; c.textBaseline = "middle";
    c.fillStyle = "#" + G.color.toString(16).padStart(6, "0"); c.fillText(G.name, 30, h / 2 + 4); const tw = c.measureText(G.name).width;
    c.font = `600 34px Inter,sans-serif`; c.fillStyle = "#cfcfd4"; c.fillText(G.sub.toUpperCase(), 60 + tw, h / 2 + 6); });
  const sw = Math.min(W * .8, 7.5), sg = plane(sign, sw, sw / 8, g, 0, WALL_H + 1.05, D / 2 - .2); sg.rotation.x = -.5;   // bord op het dak, iets achterover
  // licht binnen
  for (const lx of [-W / 4, W / 4]) { const lamp = new THREE.PointLight(0xfff2e0, 30, 16, 1.3); lamp.position.set(lx, WALL_H - .3, .5); g.add(lamp); fx.lights.push(lamp); }
  const glow = new THREE.PointLight(G.color, 12, 10, 1.5); glow.position.set(0, 1.2, -D / 2 + .8); g.add(glow);
  const strip = mesh(B(W * .7, .06, .2), mat(0xffffff, { e: 0xffffff, ei: 2 }), 0, WALL_H - .2, 0, g); strip.castShadow = false;
  // vlak voor de deur: gevarenstrepen
  const haz = canvasTex(512, 32, (c, w, h) => { for (let x = -32; x < w; x += 32) { c.fillStyle = "#111"; c.fillRect(0, 0, w, h); } for (let x = -32; x < w + 32; x += 32) { c.fillStyle = "#" + G.color.toString(16).padStart(6, "0"); c.beginPath(); c.moveTo(x, h); c.lineTo(x + 16, 0); c.lineTo(x + 32, 0); c.lineTo(x + 16, h); c.fill(); } });
  const hz = new THREE.Mesh(new THREE.PlaneGeometry(W, .35), new THREE.MeshStandardMaterial({ map: haz })); hz.rotation.x = -Math.PI / 2; hz.position.set(0, .01, D / 2 - .2); g.add(hz);
  return g;
}

function furnish() {
  const [dir, red, pit, jij] = GARAGES.map(G => G.group);
  // --- DIRECTIE: twee bureaus, whiteboard met weekplan, bank, prijzenkast ---
  desk(dir, -3, -2.5, "strateeg", BLUE); desk(dir, 1.8, -2.5, "hoofdredacteur", BLUE);
  boards.plan = canvasTex(1024, 512, drawPlanBoard);
  mesh(B(4.2, 2.2, .08), mat(0xdedede), -.6, 2.5, -4.3, dir); plane(boards.plan, 4.0, 2.0, dir, -.6, 2.5, -4.25);
  mesh(B(2.6, .5, .9), mat(0x2a2a30), 3.4, .25, 2.4, dir); mesh(B(2.6, .7, .25), mat(0x2a2a30), 3.4, .7, 2.9, dir);
  mesh(B(2.6, .12, .9), mat(PINK, { e: PINK, ei: .2 }), 3.4, .55, 2.4, dir);
  const shelf = mesh(B(.5, 2.6, 2.2), mat(0x18181b), -5.0, 1.3, 1.6, dir);
  for (let i = 0; i < 3; i++) { mesh(new THREE.CylinderGeometry(.12, .18, .5, 10), mat(0xd4af37, { m: .9, r: .25 }), -4.95, .75 + i * .8, 1.1 + i * .4, dir); mesh(new THREE.SphereGeometry(.16, 10, 8), mat(0xd4af37, { m: .9, r: .25 }), -4.95, 1.1 + i * .8, 1.1 + i * .4, dir); }
  plane(neonText("PLAN", "#5BC0FF", 4, 1), 2.2, .55, dir, 3.6, 3.3, -4.3);

  // --- REDACTIE: vier bureaus, auto op de brug, bandenstapels, gereedschapswand, koffie ---
  desk(red, -5, 1.2, "battle", PINK); desk(red, -1.6, 1.2, "podcast", LIME); desk(red, 1.8, 1.2, "nieuws", ORANGE); desk(red, 5.2, 1.2, "community", 0xb388ff);
  // brug met auto achterin
  const steel = mat(0x2a2b30, { m: .7, r: .35 });
  for (const sx of [-2.3, 2.3]) mesh(B(.35, 3.2, .35), steel, sx, 1.6, -2.6, red);
  mesh(B(4.9, .12, .25), steel, 0, 3.15, -2.6, red);
  for (const sx of [-1.1, 1.1]) mesh(B(.25, .1, 3.4), mat(0x111111), sx, 1.58, -2.5, red);
  fx.liftCar = makeCar(PINK, red, 0, 1.62, -2.5, 0, .85);
  tireStack(red, -6.6, -3.4, 5, LIME); tireStack(red, -5.8, -3.6, 3); tireStack(red, 6.6, -3.4, 4, PINK); tireStack(red, 6.6, -2.6, 2);
  // gereedschapswand
  const pb = canvasTex(512, 256, (c, w, h) => { c.fillStyle = "#3a3d44"; c.fillRect(0, 0, w, h); c.fillStyle = "#2a2c32"; for (let y = 8; y < h; y += 18) for (let x = 8; x < w; x += 18) c.fillRect(x, y, 4, 4);
    const t = ["#d33", "#C6FF00", "#ddd", "#FF2E88", "#ddd", "#5BC0FF"]; for (let i = 0; i < 14; i++) { c.fillStyle = t[i % t.length]; c.fillRect(20 + i * 35, 40 + (i % 3) * 60, 10, 70 + (i % 2) * 30); } });
  plane(pb, 3.2, 1.6, red, 4.3, 2.4, -4.35);
  mesh(B(1.4, 1.1, .7), mat(0xc4161c, { r: .35, m: .4 }), 5.8, .55, -3.8, red);
  for (let i = 0; i < 4; i++) mesh(B(1.3, .03, .02), mat(0x888888, { m: .9 }), 5.8, .25 + i * .25, -3.44, red);
  mesh(B(.7, 1.8, .6), mat(0x222226), -6.8, .9, 3.6, red); mesh(B(.4, .3, .05), mat(LIME, { e: LIME, ei: 1 }), -6.8, 1.4, 3.31, red);
  plane(neonText("SIDEWAYS WIRE", "#C6FF00", 8, 1), 6.5, .8, red, -3.2, 3.5, -4.32);

  // --- PITWALL: lange console met schermen, timingbord, vlaggen ---
  for (const [x, id] of [[-4.2, "qc"], [-1.4, "scout"], [1.4, "analist"], [4.2, "tags"]]) desk(pit, x, -1.2, id, PINK);
  boards.timing = canvasTex(1024, 384, drawTiming);
  mesh(B(9.6, 2.4, .2), mat(0x0a0a0c), 0, 2.9, -4.3, pit); plane(boards.timing, 9.4, 2.2, pit, 0, 2.9, -4.18);
  for (const sx of [-5.6, 5.6]) { mesh(new THREE.CylinderGeometry(.04, .04, 2.4, 6), mat(0x999999, { m: .8 }), sx, 1.2, 3.6, pit);
    const fl = canvasTex(64, 64, (c) => { for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) { c.fillStyle = (x + y) % 2 ? "#111" : "#fff"; c.fillRect(x * 8, y * 8, 8, 8); } });
    const f = plane(fl, .9, .6, pit, sx + .45, 2.1, 3.6); f.material.side = THREE.DoubleSide; fx.flags = (fx.flags || []).concat(f); }
  tireStack(pit, -6, 3.5, 3, PINK); tireStack(pit, 6, 3.5, 3, LIME);

  // --- JOUW GARAGE: jouw bureau met stapel, serverkast met Mac Studio, scorebord ---
  const my = desk(jij, -1.4, -1.6, "joshua", ORANGE);
  my.traverse(o => { if (o.isMesh) { o.userData.agent = "joshua"; clickables.push(o); } });
  fx.pile = new THREE.Group(); fx.pile.position.set(-2.2, .95, -1.4); jij.add(fx.pile);
  const rack = new THREE.Group(); rack.position.set(3.6, 0, -3.6); jij.add(rack);
  mesh(B(1.4, 2.6, 1.0), mat(0x0d0d10, { m: .5, r: .4 }), 0, 1.3, 0, rack);
  mesh(B(.9, .45, .9), mat(0xc9ccd1, { m: .8, r: .25 }), 0, 1.0, .1, rack);     // Mac Studio
  for (let i = 0; i < 8; i++) { const l = mesh(B(.08, .05, .02), mat(0x222222, { e: i % 2 ? LIME : BLUE, ei: 0 }), -.45 + (i % 4) * .3, 1.7 + Math.floor(i / 4) * .25, .51, rack); blinkers.push(l); }
  rack.traverse(o => { if (o.isMesh) { o.userData.agent = "mac"; clickables.push(o); } });
  boards.score = canvasTex(1024, 512, drawScore);
  mesh(B(4.6, 2.4, .2), mat(0x0a0a0c), -1.4, 2.8, -4.3, jij); plane(boards.score, 4.4, 2.2, jij, -1.4, 2.8, -4.18);
  makeCar(LIME, jij, 2.8, 0, 1.8, -.5, .8);
  tireStack(jij, -4.8, 3.4, 4, ORANGE);
}

// ---------- borden ----------
function drawPlanBoard(g, w, h) {
  g.fillStyle = "#f4f4f2"; g.fillRect(0, 0, w, h);
  g.fillStyle = "#1a1a1a"; g.font = "700 56px 'Permanent Marker','Comic Sans MS',cursive"; g.fillText("WEEKPLAN", 40, 80);
  const a = (typeof AG!=='undefined'?AG:{}).strateeg || {};
  const lines = String(a.plan || a.doing || "volgt maandag").split(/\n|(?<=\.)\s/).filter(Boolean).slice(0, 5);
  g.font = "36px 'Comic Sans MS',cursive"; g.fillStyle = "#1c4fd1";
  lines.forEach((l, i) => g.fillText("• " + l.slice(0, 44), 40, 150 + i * 62));
  g.strokeStyle = "#FF2E88"; g.lineWidth = 6; g.beginPath(); g.arc(w - 150, 110, 70, 0, 6.3); g.stroke(); g.fillStyle = "#FF2E88"; g.font = "700 40px sans-serif"; g.fillText("DM!", w - 190, 125);
}
function stats() {
  const hasS = typeof S !== "undefined" && S; const P = hasS ? posts() : [];
  return { ready: P.filter(p => ["ready", "approved"].includes(p.status)).length, rev: hasS ? toReview().length : 0,
    posted: P.filter(p => p.status === "posted").length };
}
function drawTiming(g, w, h) {
  g.fillStyle = "#050506"; g.fillRect(0, 0, w, h);
  g.font = "700 40px monospace"; g.fillStyle = "#FF2E88"; g.fillText("PITWALL  ·  LIVE", 30, 52);
  const ids = ["battle", "podcast", "nieuws", "community", "qc", "scout", "analist", "tags"];
  g.font = "30px monospace";
  ids.forEach((id, i) => { const a = (typeof AG!=='undefined'?AG:{})[id] || {}, st = a.state || "wacht";
    const x = 30 + (i % 2) * 500, y = 110 + Math.floor(i / 2) * 64;
    g.fillStyle = STC[st] || "#999"; g.fillRect(x, y - 24, 14, 28);
    g.fillStyle = "#fff"; g.fillText(String(i + 1).padStart(2, "0") + " " + (AGENTS[id].role.split("-")[0]).toUpperCase().slice(0, 12).padEnd(12), x + 26, y);
    g.fillStyle = STC[st] || "#999"; g.fillText(st.toUpperCase(), x + 330, y); });
}
function drawScore(g, w, h) {
  const s = stats(); g.fillStyle = "#050506"; g.fillRect(0, 0, w, h);
  const cell = (x, lab, val, col) => { g.fillStyle = "#9a9aa0"; g.font = "600 34px Inter,sans-serif"; g.fillText(lab, x, 90);
    g.fillStyle = col; g.font = "700 150px 'Bebas Neue',Impact,sans-serif"; g.fillText(String(val), x, 260); };
  cell(40, "WACHT OP JOU", s.rev, s.rev ? "#FF2E88" : "#C6FF00"); cell(400, "VOORRAAD", s.ready, "#5BC0FF"); cell(720, "LIVE", s.posted, "#fff");
  g.fillStyle = "#C6FF00"; g.fillRect(0, h - 22, w, 22);
}

// ---------- terrein ----------
function grounds() {
  const as = asphaltTex();
  const ground = new THREE.Mesh(new THREE.PlaneGeometry(90, 60), new THREE.MeshStandardMaterial({ map: as, roughness: .95 }));
  ground.rotation.x = -Math.PI / 2; ground.position.set(0, -.02, 10); ground.receiveShadow = true; scene.add(ground);
  // driftauto die donuts draait
  fx.car = makeCar(0xf2f2f2, scene, 0, 0, 12, 0, 1);
  fx.car.traverse(o => { if (o.isMesh && o.material.color && o.material.color.getHex() === 0xf2f2f2) o.material = mat(0xf4f4f6, { r: .2, m: .5 }); });
  // rook
  const smokeTex = canvasTex(64, 64, (g) => { const gr = g.createRadialGradient(32, 32, 2, 32, 32, 32); gr.addColorStop(0, "rgba(230,230,235,.55)"); gr.addColorStop(1, "rgba(230,230,235,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); });
  for (let i = 0; i < 60; i++) { const s = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTex, transparent: true, depthWrite: false, opacity: 0 })); s.userData.life = 0; scene.add(s); fx.smoke.push(s); }
  // pionnen en bandenmuur rond het pad
  for (let i = 0; i < 10; i++) { const a = i / 10 * Math.PI * 2; const c = mesh(new THREE.ConeGeometry(.25, .7, 10), mat(i % 2 ? LIME : PINK, { e: i % 2 ? LIME : PINK, ei: .15 }), Math.cos(a) * 9, .35, 12 + Math.sin(a) * 6.5, scene); }
  for (let x = -26; x <= 26; x += 1.1) tireStack(scene, x, 24, 2, Math.round(x) % 4 === 0 ? PINK : null);
  // betonblokken met strepen langs de zijkant
  const jb = canvasTex(256, 64, (c, w, h) => { for (let x = 0; x < w; x += 32) { c.fillStyle = (x / 32) % 2 ? "#C6FF00" : "#111"; c.fillRect(x, 0, 32, h); } });
  for (const [x, z, r] of [[-30, 8, Math.PI / 2], [-30, 14, Math.PI / 2], [30, 8, Math.PI / 2], [30, 14, Math.PI / 2]]) { const b = mesh(B(5.5, 1, .7), new THREE.MeshStandardMaterial({ map: jb }), x, .5, z, scene); b.rotation.y = r; }
  // lichtmasten
  for (const x of [-28, 28]) { mesh(new THREE.CylinderGeometry(.12, .15, 9, 8), mat(0x222226, { m: .6 }), x, 4.5, 20, scene); mesh(B(1.6, .5, .5), mat(0xffffff, { e: 0xffffff, ei: 2 }), x, 9, 20, scene);
    const sp = new THREE.SpotLight(0xfff4e0, 0, 60, .7, .5, 1.2); sp.position.set(x, 9, 20); sp.target.position.set(0, 0, 10); scene.add(sp, sp.target); fx.flood = (fx.flood || []).concat(sp); }
  // groot logo op de grond bij de ingang
  const img = new Image(); img.onload = () => { const t = canvasTex(1024, 256, (c, w, h) => c.drawImage(img, 0, 0, w, h)); const o = new THREE.Mesh(new THREE.PlaneGeometry(10, 2.5), new THREE.MeshBasicMaterial({ map: t, transparent: true, opacity: .9, toneMapped: false })); o.rotation.x = -Math.PI / 2; o.position.set(0, .02, 20.5); scene.add(o); };
  img.src = "assets/woordmerk_kleur.svg";
}

// ---------- status op de poppetjes ----------
function stateOf(id) { const a = (typeof AG!=='undefined'?AG:{})[id] || {}, c = (((typeof AGCFG!=='undefined'?AGCFG:{}).agents) || {})[id] || {}; return c.on === false ? "uit" : (a.state || "wacht"); }
function applyStates() {
  for (const [id, A] of Object.entries(AGENTS)) {
    const st = stateOf(id), o = agentObj[id]; if (!o) continue;
    o.p.visible = st !== "uit";
    const a = (typeof AG!=='undefined'?AG:{})[id] || {};
    let txt = st === "fout" ? "Hulp! " + ((a.errors || []).slice(-1)[0] || "er ging iets mis") : st === "bezig" ? (a.doing || "aan het werk") : st === "gepland" ? "zzz" : "";
    if (txt.length > 46) txt = txt.slice(0, 44) + "…";
    o.bub.element.textContent = txt; o.bub.element.className = "of3-bub of3-" + st; o.hasTxt = !!txt;
    o.tag.element.innerHTML = `<i style="background:${STC[st]}"></i>${A.role}`;
    const sm = screens[id]; if (sm) { sm.emissive.setHex(st === "bezig" ? LIME : st === "fout" ? PINK : st === "gepland" ? 0x0b2233 : 0x1a2a33); sm.emissiveIntensity = st === "bezig" ? 1.4 : 1; }
    o.st = st;
  }
  const js = screens.joshua; if (js) js.emissive.setHex(ORANGE);
  // stapel op jouw bureau
  const s = stats(); while (fx.pile.children.length) fx.pile.remove(fx.pile.children[0]);
  for (let i = 0; i < Math.min(14, Math.ceil(s.rev / 3)); i++) mesh(B(.32, .035, .42), mat(i % 2 ? 0xffffff : 0xe8e8e8), (Math.random() - .5) * .03, i * .04, 0, fx.pile);
  redraw(boards.timing, drawTiming); redraw(boards.score, drawScore); redraw(boards.plan, drawPlanBoard);
  fx.macBusy = ["battle", "podcast", "nieuws", "community"].some(id => stateOf(id) === "bezig");
  // dag en nacht
  const h = hourNL(), night = h < 7 || h >= 18;
  scene.background.setHex(night ? 0x07070d : h < 9 || h >= 16 ? 0x3b2d3a : 0x8fb7d6);
  scene.fog.color.copy(scene.background);
  fx.sun.intensity = night ? .25 : 2.2; fx.hemi.intensity = night ? .35 : 1.0;
  (fx.flood || []).forEach(s => s.intensity = night ? 900 : 0);
  fx.lights.forEach(l => l.intensity = night ? 34 : 14);
}

// ---------- animatie ----------
function tick() {
  raf = requestAnimationFrame(tick);
  const dt = Math.min(.05, clock.getDelta()); fx.t += dt; const t = fx.t;
  for (const [id, o] of Object.entries(agentObj)) {
    const st = o.st, u = o.p.userData;
    if (st === "bezig") { u.arms[0].rotation.x = 1.1 + Math.sin(t * 18) * .12; u.arms[1].rotation.x = 1.1 + Math.cos(t * 18) * .12; u.head.rotation.x = Math.sin(t * 2) * .05; u.body.position.x = 0; }
    else if (st === "fout") { u.body.position.x = Math.sin(t * 40) * .04; u.arms[0].rotation.x = 2.6 + Math.sin(t * 10) * .4; u.arms[1].rotation.x = 2.6 + Math.cos(t * 10) * .4; }
    else if (st === "gepland") { u.head.rotation.x = .45; u.head.rotation.z = .15; u.body.position.x = 0; u.arms[0].rotation.x = u.arms[1].rotation.x = u.seated ? .6 : 0; }
    else { u.head.rotation.x = 0; u.head.rotation.y = Math.sin(t * .7 + id.length) * .35; u.body.position.x = 0; u.arms[0].rotation.x = u.arms[1].rotation.x = u.seated ? .9 : Math.sin(t * 2) * .05; }
  }
  // systeemwachter loopt zijn ronde over het terrein
  const w = agentObj.wachter; if (w) { const a = t * .18; w.p.position.set(Math.sin(a) * 27, 0, 4.2);
    w.p.rotation.y = Math.cos(a) > 0 ? -Math.PI / 2 : Math.PI / 2; const u = w.p.userData; u.arms[0].rotation.x = Math.sin(t * 6) * .6; u.arms[1].rotation.x = -Math.sin(t * 6) * .6; }
  // driftauto: donuts, schuin, wielen draaien, rook
  if (fx.car) { const a = t * .9, rx = 7, rz = 4.5;
    fx.car.position.set(Math.cos(a) * rx, 0, 12 + Math.sin(a) * rz);
    const dir = Math.atan2(-Math.sin(a) * rx, Math.cos(a) * rz); fx.car.rotation.y = dir + .7; fx.car.rotation.z = Math.sin(t * 3) * .02;
    fx.car.userData.wheels.forEach(wh => wh.rotation.x += dt * 25);
    if (Math.random() < .9) { const s = fx.smoke.find(s => s.userData.life <= 0); if (s) { const back = new THREE.Vector3(Math.random() - .5, .4, -1.9).applyMatrix4(fx.car.matrixWorld);
      s.position.copy(back); s.userData.life = 1; s.scale.setScalar(.6); } } }
  for (const s of fx.smoke) if (s.userData.life > 0) { s.userData.life -= dt * .45; s.position.y += dt * .6; s.scale.multiplyScalar(1 + dt * 1.3); s.material.opacity = Math.max(0, s.userData.life) * .5; }
  // brug zakt en stijgt rustig, wiel draait als de redactie bezig is
  if (fx.liftCar) fx.liftCar.position.y = 1.62 + Math.sin(t * .4) * .12;
  blinkers.forEach((b, i) => b.material.emissiveIntensity = fx.macBusy ? (Math.sin(t * 8 + i * 1.7) > 0 ? 2.5 : .1) : .15);
  (fx.flags || []).forEach((f, i) => f.rotation.y = Math.sin(t * 3 + i) * .35);
  // foutlampen
  for (const o of Object.values(agentObj)) if (o.alarm) o.alarm.intensity = o.st === "fout" ? (Math.sin(t * 10) > 0 ? 8 : 0) : 0;
  const far = camera.position.distanceTo(controls.target) > 26;
  for (const o of Object.values(agentObj)) { o.tag.visible = !far; o.bub.visible = !!o.hasTxt && (!far || o.st === "fout" || o.st === "bezig"); }
  if (camGoal) { const k = 1 - Math.pow(.02, dt); camera.position.lerp(camGoal.pos, k); controls.target.lerp(camGoal.look, k); if (camera.position.distanceTo(camGoal.pos) < .05) camGoal = null; }
  controls.update(); renderer.render(scene, camera); labelR.render(scene, camera);
}

// ---------- camera's ----------
const VIEWS = {
  overzicht: { pos: [0, 25, 37], look: [0, 0, 1] },
  directie: { pos: [-21, 14, 5], look: [-21, .5, -6.2] }, redactie: { pos: [-6, 17, 4.5], look: [-6, .3, -5.8] },
  pitwall: { pos: [10.5, 15, 6], look: [10.5, .5, -6.2] }, jij: { pos: [24.5, 14, 5], look: [24.5, .5, -6.2] }, pad: { pos: [0, 7, 30], look: [0, 0, 12] },
};
function go(v) { const V = VIEWS[v]; if (!V) return; camGoal = { pos: new THREE.Vector3(...V.pos), look: new THREE.Vector3(...V.look) };
  document.querySelectorAll("#of3-views button").forEach(b => b.classList.toggle("on", b.dataset.v === v)); }

// ---------- bouwen ----------
function build() {
  box = document.getElementById("of3");
  renderer = new THREE.WebGLRenderer({ antialias: true, powerPreference: "high-performance" });
  renderer.setPixelRatio(Math.min(2, devicePixelRatio)); renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
  renderer.toneMapping = THREE.ACESFilmicToneMapping; renderer.outputColorSpace = THREE.SRGBColorSpace;
  box.appendChild(renderer.domElement);
  labelR = new CSS2DRenderer(); labelR.domElement.className = "of3-labels"; box.appendChild(labelR.domElement);
  scene = new THREE.Scene(); scene.background = new THREE.Color(0x07070d); scene.fog = new THREE.Fog(0x07070d, 45, 95);
  camera = new THREE.PerspectiveCamera(42, 2, .1, 200); camera.position.set(0, 25, 37);
  controls = new OrbitControls(camera, labelR.domElement); controls.target.set(0, 0, 0); controls.enableDamping = true;
  controls.maxPolarAngle = 1.35; controls.minDistance = 5; controls.maxDistance = 70;
  controls.addEventListener("start", () => camGoal = null);
  fx.hemi = new THREE.HemisphereLight(0xbfd6ff, 0x1a1a20, 1); scene.add(fx.hemi);
  fx.sun = new THREE.DirectionalLight(0xffffff, 2.2); fx.sun.position.set(-18, 30, 22); fx.sun.castShadow = true;
  fx.sun.shadow.mapSize.set(2048, 2048); Object.assign(fx.sun.shadow.camera, { left: -40, right: 40, top: 30, bottom: -30, far: 90 }); fx.sun.shadow.bias = -.0005; scene.add(fx.sun);
  clock = new THREE.Clock();
  GARAGES.forEach(garage); furnish(); grounds();
  for (const [id, A] of Object.entries(AGENTS)) {
    const G = GARAGES.find(g => g.id === A.g).group;
    const p = person(G, A.look, A.at[0], A.at[1] - (A.stand ? 0 : .95), id, !A.stand);
    if (!A.stand) p.rotation.y = Math.PI;       // gezicht naar voren, naar jou
    if (A.stand) { scene.add(p); }
    const tag = label("", "of3-tag", p, A.stand ? 2.3 : 2.2), bub = label("", "of3-bub", p, A.stand ? 3.0 : 2.9);
    const alarm = new THREE.PointLight(PINK, 0, 5); alarm.position.set(0, 3, 0); p.add(alarm);
    agentObj[id] = { p, tag, bub, alarm, st: "wacht" };
  }
  const ray = new THREE.Raycaster(), m = new THREE.Vector2(); let down = null;
  labelR.domElement.addEventListener("pointerdown", e => down = [e.clientX, e.clientY]);
  labelR.domElement.addEventListener("pointerup", e => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 6) return;
    const r = renderer.domElement.getBoundingClientRect(); m.set((e.clientX - r.left) / r.width * 2 - 1, -(e.clientY - r.top) / r.height * 2 + 1);
    ray.setFromCamera(m, camera); const hit = ray.intersectObjects(clickables, false).find(h => h.object.visible);
    if (hit) { pick = hit.object.userData.agent; window.officePick && window.officePick(pick);
      const A = AGENTS[pick]; if (A) go(A.g); if (pick === "joshua" || pick === "mac") go("jij"); }
  });
  new ResizeObserver(resize).observe(box); resize();
  ready = true; tick();
}
function resize() { if (!box) return; const w = box.clientWidth, h = Math.max(380, Math.round(w * .56)); box.style.height = h + "px";
  renderer.setSize(w, h); labelR.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); }

window.office3d = {
  start() { try { if (!ready) build(); else if (!raf) tick(); applyStates(); return true; } catch (e) { console.error("kantoor 3D:", e); return false; } },
  update() { if (ready) applyStates(); },
  stop() { cancelAnimationFrame(raf); raf = 0; },
  go,
};
window.dispatchEvent(new Event("office3d-ready"));
