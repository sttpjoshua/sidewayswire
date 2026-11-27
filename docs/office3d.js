// KANTOOR 3D: het Sideways Wire-terrein. Vier garages rond een driftpad, met de agents als poppetjes.
// Gegevens: docs/agents/<id>.json + data/agents.json (via loadAgents in index.html) en status.json (posts).
// Alles is zelf opgebouwd uit simpele vormen (geen modellen van anderen), in de kleuren van Sideways Wire.
import * as THREE from "three";
import { OrbitControls } from "./vendor/three/OrbitControls.js";
import { CSS2DRenderer, CSS2DObject } from "./vendor/three/CSS2DRenderer.js";
import { EffectComposer } from "./vendor/three/postprocessing/EffectComposer.js";
import { RenderPass } from "./vendor/three/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "./vendor/three/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "./vendor/three/postprocessing/OutputPass.js";
import { GLTFLoader } from "./vendor/three/loaders/GLTFLoader.js";

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
  car.userData.paint = paint;
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
  // twee soorten benen: zittend en staand (om te lopen); de romp gaat mee omhoog bij opstaan
  const sitL = new THREE.Group(), standL = new THREE.Group(); body.add(sitL, standL);
  mesh(B(.22, .2, .6), pa, -.13, .6, -.15, sitL); mesh(B(.22, .2, .6), pa, .13, .6, -.15, sitL); mesh(B(.2, .55, .2), pa, -.13, .3, -.42, sitL); mesh(B(.2, .55, .2), pa, .13, .3, -.42, sitL);
  const legs = [];
  for (const sx of [-.13, .13]) { const L = new THREE.Group(); L.position.set(sx, .85, 0); standL.add(L); mesh(B(.22, .82, .22), pa, 0, -.42, 0, L); mesh(B(.24, .1, .32), mat(0x111111), 0, -.83, -.05, L); legs.push(L); }
  const upper = new THREE.Group(); body.add(upper);
  const torso = mesh(new THREE.CapsuleGeometry(.27, .45, 4, 10), sh, 0, 1.22, 0, upper);
  // logo op de rug: limestreep
  mesh(B(.3, .06, .02), mat(LIME, { e: LIME, ei: .3 }), 0, torso.position.y + .1, .27, upper);
  const head = new THREE.Group(); head.position.set(0, torso.position.y + .58, 0); upper.add(head);
  mesh(new THREE.SphereGeometry(.24, 16, 12), sk, 0, 0, 0, head);
  mesh(B(.05, .05, .02), mat(0x111111), -.08, .03, -.23, head); mesh(B(.05, .05, .02), mat(0x111111), .08, .03, -.23, head);
  if (extra === "cap") { mesh(new THREE.SphereGeometry(.25, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2), hc, 0, .06, 0, head); mesh(B(.3, .03, .2), hc, 0, .08, -.25, head); }
  else if (extra === "beanie") { mesh(new THREE.SphereGeometry(.26, 14, 8, 0, Math.PI * 2, 0, Math.PI / 1.9), hc, 0, .04, 0, head); mesh(new THREE.SphereGeometry(.06, 8, 6), hc, 0, .3, 0, head); }
  else { mesh(new THREE.SphereGeometry(.25, 14, 8, 0, Math.PI * 2, 0, Math.PI / 2.2), hc, 0, .05, .02, head); }
  if (extra === "headset") { mesh(new THREE.TorusGeometry(.26, .03, 6, 16, Math.PI), mat(0x111111), 0, .04, 0, head); mesh(B(.08, .14, .1), mat(LIME, { e: LIME, ei: .4 }), -.26, 0, 0, head); mesh(B(.08, .14, .1), mat(LIME, { e: LIME, ei: .4 }), .26, 0, 0, head); }
  const arms = [];
  for (const s of [-1, 1]) { const a = new THREE.Group(); a.position.set(s * .33, torso.position.y + .25, 0); upper.add(a);
    mesh(B(.15, .5, .15), sh, 0, -.22, 0, a); mesh(B(.13, .13, .13), sk, 0, -.5, 0, a); a.rotation.x = seated ? 1.1 : 0; arms.push(a); }
  p.userData = { id, body, head, arms, legs, sitL, standL, upper, seated, baseY: 0 };
  pose(p, seated);
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

function pose(p, sit) { const u = p.userData; u.sitL.visible = sit; u.standL.visible = !sit; u.upper.position.y = sit ? 0 : .15; u.sitting = sit; }

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
    let fs = 34; c.font = `600 ${fs}px Inter,sans-serif`; while (fs > 16 && 60 + tw + c.measureText(G.sub.toUpperCase()).width > w - 24) { fs -= 2; c.font = `600 ${fs}px Inter,sans-serif`; }
    c.fillStyle = "#cfcfd4"; c.fillText(G.sub.toUpperCase(), 60 + tw, h / 2 + 6); });
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
  makeCar(0x2a2b30, jij, 2.8, 0, 1.8, -.5, .8);
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
  // led-bord aan de rand van het pad
  boards.bill = canvasTex(1024, 384, drawBillboard);
  const bb = new THREE.Group(); bb.position.set(-17, 0, 15); bb.rotation.y = .55; scene.add(bb);
  for (const sx of [-2.6, 2.6]) mesh(new THREE.CylinderGeometry(.12, .12, 4, 8), mat(0x222226, { m: .6 }), sx, 2, 0, bb);
  mesh(B(6.4, 2.6, .3), mat(0x0a0a0c), 0, 4.2, 0, bb); plane(boards.bill, 6.2, 2.4, bb, 0, 4.2, .16);
  // groot logo op de grond bij de ingang
  const img = new Image(); img.onload = () => { const t = canvasTex(1024, 256, (c, w, h) => c.drawImage(img, 0, 0, w, h)); const o = new THREE.Mesh(new THREE.PlaneGeometry(10, 2.5), new THREE.MeshBasicMaterial({ map: t, transparent: true, opacity: .9, toneMapped: false })); o.rotation.x = -Math.PI / 2; o.position.set(0, .02, 20.5); scene.add(o); };
  img.src = "assets/woordmerk_kleur.svg";
}


// ---------- lopen: wie wacht, staat soms op voor koffie, de bank, het driftpad of jouw bureau ----------
const GZ = -6, FRONT = GZ + DEPTH / 2 + 1.3;
const gx = id => GARAGES.find(g => g.id === id).x;
const SPOTS = {
  koffie: () => [[gx("redactie") - 6.8 + 1.0, FRONT], [gx("redactie") - 6.0, GZ + 3.0]],
  bank: () => [[gx("directie") + 3.4, FRONT], [gx("directie") + 3.4, GZ + 2.4]],
  pad: () => { const x = (Math.random() - .5) * 14; return [[x, 4.5]]; },
  jij: () => [[gx("jij") - 1.4, FRONT], [gx("jij") - 1.4, GZ + .4]],
};
const SAY = { koffie: ["koffie halen ☕", "even een bakkie", "espresso, dubbel"], bank: ["even zitten", "pauze", "brainstormen op de bank"],
  pad: ["even kijken naar die donuts", "wat een rook!", "die hoek kan dieper"], jij: ["clip voor je op de stapel", "even overleggen met jou", "kijk deze eens"] };
function startWalk(id) {
  const o = agentObj[id], A = AGENTS[id]; if (!o || o.walk || A.stand) return;
  const G = GARAGES.find(g => g.id === A.g), dest = Object.keys(SPOTS)[Math.floor(Math.random() * 4)];
  const seat = new THREE.Vector3(); o.p.getWorldPosition(seat);
  const out = [[seat.x, seat.z + 1.2], [seat.x, FRONT]], there = SPOTS[dest]();
  const go = [...out, ...there].map(([x, z]) => new THREE.Vector3(x, 0, z));
  o.home = { parent: o.p.parent, pos: o.p.position.clone(), rot: o.p.rotation.y };
  scene.attach(o.p); pose(o.p, false);
  o.walk = { path: go, i: 0, phase: "heen", wait: 0, dest, back: [...go].reverse().slice(1).concat([seat.clone()]) };
  o.say = SAY[dest][Math.floor(Math.random() * SAY[dest].length)];
}
function stepWalk(o, dt, t) {
  const W = o.walk, u = o.p.userData;
  if (W.wait > 0) { W.wait -= dt; u.legs.forEach(l => l.rotation.x = 0); u.arms.forEach(a => a.rotation.x = W.dest === "koffie" ? .9 : 0);
    if (W.wait <= 0) { W.path = W.back; W.i = 0; W.phase = "terug"; if (W.dest === "jij") fly(o.p, true); } return; }
  const target = W.path[W.i]; if (!target) { // thuis
    o.home.parent.attach(o.p); o.p.position.copy(o.home.pos); o.p.rotation.set(0, o.home.rot, 0); pose(o.p, true); o.walk = null; o.say = null; return; }
  const d = target.clone().sub(o.p.position); d.y = 0; const dist = d.length();
  if (dist < .08) { W.i++; if (W.i >= W.path.length && W.phase === "heen") {
      if (W.dest === "custom") { W.wait = W.waitFor || 5; W.arrived = true; if (W.onArrive) W.onArrive(); } else W.wait = 5 + Math.random() * 5;
      if (W.dest === "bank") pose(o.p, true); } return; }
  const sp = 2.1 * dt; o.p.position.add(d.multiplyScalar(Math.min(1, sp / dist)));
  o.p.rotation.y = Math.atan2(-(target.x - o.p.position.x), -(target.z - o.p.position.z));
  u.legs[0].rotation.x = Math.sin(t * 9) * .6; u.legs[1].rotation.x = -Math.sin(t * 9) * .6;
  u.arms[0].rotation.x = -Math.sin(t * 9) * .5; u.arms[1].rotation.x = Math.sin(t * 9) * .5; u.head.rotation.set(0, 0, 0);
}

// ---------- clips vliegen van de redactie naar jouw stapel ----------
const flying = [];
let clipTex;
function fly(fromObj, big) {
  if (!fx.pile) return; clipTex = clipTex || canvasTex(128, 160, (g, w, h) => { g.fillStyle = "#111"; g.fillRect(0, 0, w, h); g.fillStyle = "#C6FF00"; g.fillRect(6, 6, w - 12, h - 40);
    g.fillStyle = "#111"; g.beginPath(); g.moveTo(52, 50); g.lineTo(84, 70); g.lineTo(52, 90); g.fill(); g.fillStyle = "#FF2E88"; g.fillRect(6, h - 26, w - 12, 14); });
  const m = new THREE.Mesh(new THREE.PlaneGeometry(.45, .56), new THREE.MeshBasicMaterial({ map: clipTex, side: THREE.DoubleSide, toneMapped: false }));
  const a = new THREE.Vector3(); fromObj.getWorldPosition(a); a.y += 2.0; const b = new THREE.Vector3(); fx.pile.getWorldPosition(b); b.y += .4;
  m.position.copy(a); if (big) m.scale.setScalar(1.4); scene.add(m); flying.push({ m, a, b, t: 0, dur: 2.2 + a.distanceTo(b) / 22 });
}
function stepFly(dt) {
  for (let i = flying.length - 1; i >= 0; i--) { const f = flying[i]; f.t += dt / f.dur; const k = Math.min(1, f.t);
    f.m.position.lerpVectors(f.a, f.b, k); f.m.position.y += Math.sin(k * Math.PI) * (4 + f.a.distanceTo(f.b) * .12);
    f.m.rotation.y += dt * 6; f.m.rotation.z = Math.sin(k * 8) * .3;
    if (k >= 1) { scene.remove(f.m); flying.splice(i, 1); pop(f.b); playPing(); } }
}

// ---------- vuurwerk als je de dagopdrachten haalt ----------
const sparks = [];
function pop(at, n = 14, colors = [LIME, PINK, BLUE, 0xffffff]) {
  for (let i = 0; i < n; i++) { const m = new THREE.Mesh(new THREE.BoxGeometry(.08, .08, .08), new THREE.MeshBasicMaterial({ color: colors[i % colors.length], toneMapped: false }));
    m.position.copy(at); const v = new THREE.Vector3((Math.random() - .5) * 3, Math.random() * 3 + 1, (Math.random() - .5) * 3); scene.add(m); sparks.push({ m, v, life: 1 }); }
}
function fireworks() {
  const x = gx("jij"); for (let k = 0; k < 6; k++) setTimeout(() => pop(new THREE.Vector3(x + (Math.random() - .5) * 8, 9 + Math.random() * 3, -4 + Math.random() * 3), 60), k * 450);
}
function stepSparks(dt) {
  for (let i = sparks.length - 1; i >= 0; i--) { const s = sparks[i]; s.life -= dt * .7; s.v.y -= 6 * dt; s.m.position.addScaledVector(s.v, dt);
    s.m.scale.setScalar(Math.max(.01, s.life)); if (s.life <= 0) { scene.remove(s.m); sparks.splice(i, 1); } }
}

// ---------- reclamebord aan het pad: volgende post en net live ----------
function drawBillboard(g, w, h) {
  const hasS = typeof S !== "undefined" && S, P = hasS ? posts() : [], now = Date.now();
  const next = P.filter(p => p.post_at && new Date(p.post_at) > now && ["ready", "approved"].includes(p.status)).sort((a, b) => a.post_at < b.post_at ? -1 : 1)[0];
  const live = P.filter(p => p.status === "posted").sort((a, b) => (a.posted_at || "") < (b.posted_at || "") ? 1 : -1)[0];
  g.fillStyle = "#050506"; g.fillRect(0, 0, w, h); g.fillStyle = "#C6FF00"; g.fillRect(0, 0, w, 10); g.fillRect(0, h - 10, w, 10);
  const when = t => new Date(t).toLocaleString("nl-NL", { timeZone: "Europe/Amsterdam", weekday: "short", hour: "2-digit", minute: "2-digit" });
  g.font = "700 38px Inter,sans-serif"; g.fillStyle = "#FF2E88"; g.fillText("VOLGENDE POST", 40, 74);
  g.fillStyle = "#9a9aa0"; g.font = "600 32px Inter,sans-serif"; g.fillText(next ? when(next.post_at) : "nog niets ingepland", 400, 74);
  g.fillStyle = "#fff"; g.font = "italic 900 64px 'Bebas Neue',Impact,sans-serif";
  const title = (next && (next.title || next.hook || "")) || ""; wrap(g, String(title).toUpperCase(), 40, 150, w - 80, 62, 2);
  g.font = "700 30px Inter,sans-serif"; g.fillStyle = "#5BC0FF"; g.fillText("NET LIVE", 40, h - 44);
  g.fillStyle = "#cfcfd4"; g.font = "500 28px Inter,sans-serif"; g.fillText(live ? String(live.title || "").slice(0, 52) : "straks vanaf 1 december", 220, h - 44);
}
function wrap(g, txt, x, y, maxW, lh, maxL) { const words = txt.split(/\s+/); let line = "", n = 0;
  for (const wd of words) { const tst = line ? line + " " + wd : wd; if (g.measureText(tst).width > maxW && line) { g.fillText(line, x, y + n * lh); line = wd; if (++n >= maxL) return; } else line = tst; }
  if (line) g.fillText(line, x, y + n * lh); }

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
    if (st !== "wacht" && o.walk && o.walk.phase === "heen") { o.walk.wait = 0.01; }      // werk komt binnen: terug naar het bureau
    const L = window.agentLevel ? agentLevel(id) : null;
    o.tag.element.innerHTML = `<i style="background:${STC[st]}"></i>${A.role}${L ? ` <b class="of3-lv">LV ${L.lvl}</b>` : ""}`;
    const sm = screens[id]; if (sm) { sm.emissive.setHex(st === "bezig" ? LIME : st === "fout" ? PINK : st === "gepland" ? 0x0b2233 : 0x1a2a33); sm.emissiveIntensity = st === "bezig" ? 1.4 : 1; }
    o.st = st;
  }
  const js = screens.joshua; if (js) js.emissive.setHex(ORANGE);
  // stapel op jouw bureau
  const s = stats(); while (fx.pile.children.length) fx.pile.remove(fx.pile.children[0]);
  for (let i = 0; i < Math.min(14, Math.ceil(s.rev / 3)); i++) mesh(B(.32, .035, .42), mat(i % 2 ? 0xffffff : 0xe8e8e8), (Math.random() - .5) * .03, i * .04, 0, fx.pile);
  redraw(boards.timing, drawTiming); redraw(boards.score, drawScore); redraw(boards.plan, drawPlanBoard); redraw(boards.bill, drawBillboard);
  // dagopdrachten gehaald: vuurwerk, een keer per dag
  try { const Q = window.officeQuests ? officeQuests() : [], d = new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Amsterdam" });
    if (Q.length && Q.every(q => q.done) && localStorage.getItem("sw-fireworks") !== d) { localStorage.setItem("sw-fireworks", d); fireworks(); } } catch (e) {}
  fx.macBusy = ["battle", "podcast", "nieuws", "community"].some(id => stateOf(id) === "bezig");
  // dag en nacht
  const h = hourNL(), night = h < 7 || h >= 18;
  scene.background.setHex(night ? 0x07070d : h < 9 || h >= 16 ? 0x3b2d3a : 0x8fb7d6);
  scene.fog.color.copy(scene.background);
  fx.sun.intensity = night ? .25 : 2.2; fx.hemi.intensity = night ? .35 : 1.0;
  (fx.flood || []).forEach(s => s.intensity = night ? 420 : 0);
  fx.lights.forEach(l => l.intensity = night ? 34 : 14);
  extrasState(night); r4State(); liveries(); keyTrouble(); r6State(night);
}

// ---------- animatie ----------
function tick() {
  raf = requestAnimationFrame(tick);
  const dt = Math.min(.05, clock.getDelta()); fx.t += dt; const t = fx.t;
  for (const [id, o] of Object.entries(agentObj)) {
    const st = o.st, u = o.p.userData;
    if (o.walk) { stepWalk(o, dt, t); continue; }
    if (st === "wacht" && !AGENTS[id].stand && Math.random() < dt / 45 && Object.values(agentObj).filter(x => x.walk).length < 3) { startWalk(id); continue; }
    if (st === "bezig" && ["battle", "podcast", "nieuws"].includes(id) && Math.random() < dt / 7) fly(o.p);
    if (st !== "gepland" && u.upper) u.upper.rotation.x = 0;
    if (st === "bezig") { u.arms[0].rotation.x = 1.1 + Math.sin(t * 18) * .12; u.arms[1].rotation.x = 1.1 + Math.cos(t * 18) * .12; u.head.rotation.x = Math.sin(t * 2) * .05; u.body.position.x = 0; }
    else if (st === "fout") { u.body.position.x = Math.sin(t * 40) * .04; u.arms[0].rotation.x = 2.6 + Math.sin(t * 10) * .4; u.arms[1].rotation.x = 2.6 + Math.cos(t * 10) * .4; }
    else if (st === "gepland") { u.upper.rotation.x = -.55; u.head.rotation.x = -.2; u.head.rotation.z = .25; u.body.position.x = 0; u.arms[0].rotation.x = u.arms[1].rotation.x = u.seated ? 1.5 : 0; }
    else { u.head.rotation.x = 0; u.head.rotation.y = Math.sin(t * .7 + id.length) * .35; u.body.position.x = 0; u.arms[0].rotation.x = u.arms[1].rotation.x = u.seated ? .9 : Math.sin(t * 2) * .05; }
  }
  // systeemwachter loopt zijn ronde over het terrein
  const w = agentObj.wachter; if (w) { const a = t * .18; w.p.position.set(Math.sin(a) * 27, 0, 4.2);
    w.p.rotation.y = Math.cos(a) > 0 ? -Math.PI / 2 : Math.PI / 2; const u = w.p.userData; u.arms[0].rotation.x = Math.sin(t * 6) * .6; u.arms[1].rotation.x = -Math.sin(t * 6) * .6;
    u.legs[0].rotation.x = -Math.sin(t * 6) * .6; u.legs[1].rotation.x = Math.sin(t * 6) * .6; }
  // driftauto: donuts, schuin, wielen draaien, rook
  if (fx.car) { const a = t * .9, rx = 7, rz = 4.5;
    fx.car.position.set(Math.cos(a) * rx, 0, 12 + Math.sin(a) * rz);
    const dir = Math.atan2(-Math.sin(a) * rx, Math.cos(a) * rz); fx.car.rotation.y = dir + .7; fx.car.rotation.z = Math.sin(t * 3) * .02;
    fx.car.userData.wheels.forEach(wh => wh.rotation.x += dt * 25);
    if (Math.random() < .9) { const s = fx.smoke.find(s => s.userData.life <= 0); if (s) { const back = new THREE.Vector3(Math.random() - .5, .4, -1.9).applyMatrix4(fx.car.matrixWorld);
      s.position.copy(back); s.userData.life = 1; s.scale.setScalar(.6); } } }
  for (const s of fx.smoke) if (s.userData.life > 0) { s.userData.life -= dt * .45; s.position.y += dt * .6; s.scale.multiplyScalar(1 + dt * 1.3); s.material.opacity = Math.max(0, s.userData.life) * .32; }
  // brug zakt en stijgt rustig, wiel draait als de redactie bezig is
  if (fx.liftCar) { const up = fx.macBusy ? 2.3 : 1.62; fx.liftCar.position.y += (up - fx.liftCar.position.y) * Math.min(1, dt * .8);
    if (fx.macBusy) fx.liftCar.userData.wheels.forEach(wh => wh.rotation.x += dt * 8); }
  stepFly(dt); stepSparks(dt);
  blinkers.forEach((b, i) => b.material.emissiveIntensity = fx.macBusy ? (Math.sin(t * 8 + i * 1.7) > 0 ? 2.5 : .1) : .15);
  (fx.flags || []).forEach((f, i) => f.rotation.y = Math.sin(t * 3 + i) * .35);
  // foutlampen
  for (const o of Object.values(agentObj)) if (o.alarm) o.alarm.intensity = o.st === "fout" ? (Math.sin(t * 10) > 0 ? 8 : 0) : 0;
  const far = camera.position.distanceTo(controls.target) > 26;
  for (const o of Object.values(agentObj)) {
    if (o.say && !o.hasTxt) { o.bub.element.textContent = o.say; o.bub.element.className = "of3-bub of3-say"; }
    const show = !!o.hasTxt || !!o.say; o.tag.visible = !far; o.bub.visible = show && (!far || o.st === "fout" || o.st === "bezig"); }
  if (camGoal) { const k = 1 - Math.pow(.02, dt); camera.position.lerp(camGoal.pos, k); controls.target.lerp(camGoal.look, k); if (camera.position.distanceTo(camGoal.pos) < .05) camGoal = null; }
  extrasTick(dt, t); r4Tick(dt, t); controls.update(); if (fx.composer) fx.composer.render(); else renderer.render(scene, camera); labelR.render(scene, camera);
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
  GARAGES.forEach(garage); furnish(); grounds(); extrasBuild(); r4Build(); r6Build();
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
function resize() { if (!box) return; const tv = box.classList.contains("tv"), w = box.clientWidth, h = tv ? box.clientHeight : Math.max(380, Math.round(w * .56));
  if (!tv) box.style.height = h + "px"; else box.style.height = "";
  renderer.setSize(w, h); labelR.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix(); if (fx.composer) fx.composer.setSize(w, h); }

window.addEventListener("office-focus", e => { const A = AGENTS[e.detail]; if (A) go(A.g); });
window.office3d = {
  start() { try { if (!ready) build(); else if (!raf) tick(); applyStates(); return true; } catch (e) { console.error("kantoor 3D:", e); return false; } },
  update() { if (ready) applyStates(); },
  stop() { cancelAnimationFrame(raf); raf = 0; },
  go, fireworks, walk: startWalk, live: liveMoment, plan: strategistBoard, livery: liveries, tv: setTV, sound: toggleSound, round: chiefRound, deliver: () => sendVan("nieuws"),
};
window.dispatchEvent(new Event("office3d-ready"));

// =====================================================================================
// RONDE 3: tv-modus, jij, tandem en publiek, podium, prestaties, groei, weer, geluid,
// bezorgers, de ochtendronde van de hoofdredacteur, direct bedienen en waarschuwingen.
// =====================================================================================
const NL = () => new Date(new Date().toLocaleString("en-US", { timeZone: "Europe/Amsterdam" }));
const todayNL = () => new Date().toLocaleDateString("sv-SE", { timeZone: "Europe/Amsterdam" });
const LS = { get(k, d) { try { return JSON.parse(localStorage.getItem(k)) ?? d; } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) {} } };
const X = { vans: [], crowd: [], growth: -1, podium: null, podiumKey: "", rain: null, snow: null, xmas: null, wx: null, me: null, car2: null, beacon: null, smoke: [] };

function followers() {
  try { const D = (typeof STATS !== "undefined" && STATS && STATS.days) || {}, k = Object.keys(D).sort().pop(); if (!k) return 0;
    return Object.values(D[k]).reduce((n, v) => n + (+v.followers || 0), 0); } catch (e) { return 0; }
}
window.officeFollowers = followers;

function extrasBuild() {
  // gloed op neon en schermen
  try { const c = new EffectComposer(renderer); c.addPass(new RenderPass(scene, camera));
    c.addPass(new UnrealBloomPass(new THREE.Vector2(512, 512), .32, .35, .97)); c.addPass(new OutputPass()); fx.composer = c; } catch (e) { fx.composer = null; }
  // jij aan je bureau
  const jij = GARAGES[3].group;
  X.me = person(jij, [0x111114, 0x1d1d22, 0xe0b090, 0x2a1a10, "cap"], -1.4, -1.6 - .95, "joshua", true); X.me.rotation.y = Math.PI;
  label(`<i style="background:#FF9F43"></i>Jij`, "of3-tag", X.me, 2.2);
  // tweede driftauto voor de tandem
  X.car2 = makeCar(LIME, scene, 0, 0, 12, 0, 1);
  // publiek achter de bandenmuur (alleen op event-dagen helemaal vol)
  const cols = [LIME, PINK, BLUE, ORANGE, 0xffffff, 0x222222];
  for (let i = 0; i < 70; i++) { const g = new THREE.Group(), x = -25 + (i % 35) * 1.45 + (Math.random() - .5) * .4, z = 25.2 + Math.floor(i / 35) * .9;
    g.position.set(x, 0, z); scene.add(g);
    mesh(new THREE.CapsuleGeometry(.22, .5, 3, 8), mat(cols[i % cols.length]), 0, .6, 0, g); mesh(new THREE.SphereGeometry(.17, 10, 8), mat([0xe8b48a, 0xc98a5e, 0x8d5a3b, 0xf1c19a][i % 4]), 0, 1.15, 0, g);
    g.userData = { ph: Math.random() * 6, keep: i % 9 === 0 }; X.crowd.push(g); }
  // groei: tribunes en een tweede pad, verborgen tot de volgers er zijn
  X.grow = [new THREE.Group(), new THREE.Group(), new THREE.Group()]; X.grow.forEach(g => { g.visible = false; scene.add(g); });
  const stand = (g, x, z, ry) => { const t = new THREE.Group(); t.position.set(x, 0, z); t.rotation.y = ry; g.add(t);
    for (let r = 0; r < 5; r++) mesh(B(12, .5, 1.1), mat(r % 2 ? 0x2a2b30 : 0x34363c), 0, .25 + r * .5, r * 1.1, t);
    mesh(B(12.4, .3, .3), mat(PINK, { e: PINK, ei: .6 }), 0, 2.7, 5.4, t);
    for (let i = 0; i < 40; i++) { const c = mesh(new THREE.SphereGeometry(.2, 8, 6), mat(cols[i % cols.length]), -5.5 + (i % 10) * 1.2, .9 + Math.floor(i / 10) * .5, Math.floor(i / 10) * 1.1, t); c.userData.ph = Math.random() * 6; X.crowd.push(c); } };
  stand(X.grow[0], -31, 12, Math.PI / 2);
  stand(X.grow[1], 31, 12, -Math.PI / 2);
  const ring = new THREE.Mesh(new THREE.TorusGeometry(34, .6, 8, 64), mat(0x1a1b1f, { m: .6 })); ring.rotation.x = Math.PI / 2; ring.position.set(0, 12, 8); X.grow[2].add(ring);
  for (let i = 0; i < 16; i++) { const a = i / 16 * Math.PI * 2; mesh(new THREE.CylinderGeometry(.3, .4, 12, 8), mat(0x1a1b1f, { m: .6 }), Math.cos(a) * 34, 6, 8 + Math.sin(a) * 34, X.grow[2]);
    mesh(B(1, .4, .6), mat(0xffffff, { e: 0xffffff, ei: 2 }), Math.cos(a) * 33, 11.6, 8 + Math.sin(a) * 33, X.grow[2]); }
  // podium aan de rand van het pad
  X.podium = new THREE.Group(); X.podium.position.set(17, 0, 17); X.podium.rotation.y = -.5; scene.add(X.podium);
  for (const [x, h, c, n] of [[0, 1.2, 0xd4af37, "1"], [-1.6, .8, 0xc0c0c8, "2"], [1.6, .5, 0xcd7f32, "3"]]) {
    mesh(B(1.5, h, 1.2), mat(0x111114), x, h / 2, 0, X.podium); mesh(B(1.52, .12, 1.22), mat(c, { m: .8, r: .3 }), x, h, 0, X.podium);
    plane(neonText(n, "#ffffff", 1, 1), .6, .6, X.podium, x, h / 2, .61); }
  plane(neonText("AGENTS VAN DE WEEK", "#C6FF00", 8, 1), 4.6, .6, X.podium, 0, 3.6, 0);
  X.podiumFigs = new THREE.Group(); X.podium.add(X.podiumFigs);
  // waarschuwingslamp op jouw garage en rook bij de serverkast
  X.beacon = new THREE.Group(); X.beacon.position.set(GARAGES[3].x + 4.5, WALL_H + .9, -6 + DEPTH / 2); scene.add(X.beacon);
  mesh(new THREE.CylinderGeometry(.22, .25, .35, 12), mat(0xff7a00, { e: 0xff7a00, ei: 0 }), 0, 0, 0, X.beacon);
  X.beaconLight = new THREE.SpotLight(0xff7a00, 0, 18, .5, .5, 1); X.beacon.add(X.beaconLight, X.beaconLight.target); X.beaconLight.target.position.set(4, -3, 0);
  const smokeTex = canvasTex(64, 64, (g) => { const gr = g.createRadialGradient(32, 32, 2, 32, 32, 32); gr.addColorStop(0, "rgba(60,60,64,.7)"); gr.addColorStop(1, "rgba(60,60,64,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); });
  for (let i = 0; i < 25; i++) { const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: smokeTex, transparent: true, depthWrite: false, opacity: 0 })); sp.userData.life = 0; scene.add(sp); X.smoke.push(sp); }
  // kerstlichtjes (alleen in december zichtbaar)
  X.xmas = new THREE.Group(); scene.add(X.xmas);
  for (const G of GARAGES) for (let i = 0; i <= 24; i++) { const x = G.x - G.w / 2 + i * G.w / 24, c = [0xff3030, LIME, 0xffd000, BLUE][i % 4];
    const b = mesh(new THREE.SphereGeometry(.09, 8, 6), new THREE.MeshBasicMaterial({ color: c, toneMapped: false }), x, WALL_H + .2 + Math.sin(i / 24 * Math.PI * 4) * .12, -6 + DEPTH / 2 + .25, X.xmas); b.castShadow = false; }
  const tree = new THREE.Group(); tree.position.set(-27, 0, 3); X.xmas.add(tree);
  for (let k = 0; k < 4; k++) mesh(new THREE.ConeGeometry(1.6 - k * .35, 1.4, 10), mat(0x1f5a2a), 0, 1 + k * .9, 0, tree);
  mesh(new THREE.OctahedronGeometry(.3), new THREE.MeshBasicMaterial({ color: 0xffd000, toneMapped: false }), 0, 4.6, 0, tree);
  // neerslag
  const mk = (n, col, size) => { const g = new THREE.BufferGeometry(), a = new Float32Array(n * 3); for (let i = 0; i < n; i++) { a[i * 3] = (Math.random() - .5) * 80; a[i * 3 + 1] = Math.random() * 25; a[i * 3 + 2] = Math.random() * 50 - 15; }
    g.setAttribute("position", new THREE.BufferAttribute(a, 3)); const pts = new THREE.Points(g, new THREE.PointsMaterial({ color: col, size, transparent: true, opacity: .75, depthWrite: false })); pts.visible = false; scene.add(pts); return pts; };
  X.rain = mk(5000, 0xaac8ff, .09); X.snow = mk(3000, 0xffffff, .18);
  X.groundMat = scene.children.find(o => o.isMesh && o.geometry.type === "PlaneGeometry" && o.geometry.parameters.width === 90)?.material;
  weather(); setInterval(weather, 15 * 60 * 1000);
  // slepen van een link naar het terrein = tip voor de nieuwsscout
  box.addEventListener("dragover", e => { e.preventDefault(); box.classList.add("drop"); });
  box.addEventListener("dragleave", () => box.classList.remove("drop"));
  box.addEventListener("drop", e => { e.preventDefault(); box.classList.remove("drop");
    const url = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text/plain") || "").split("\n").find(l => /^https?:\/\//.test(l.trim()));
    if (!url) return; const sc = agentObj.scout; if (sc) { sc.say = "Ik pak hem op!"; sc.hasTxt = false; setTimeout(() => sc.say = null, 5000); }
    go("pitwall"); setTimeout(() => { location.hash = "#agents"; setTimeout(() => { const i = document.getElementById("tip-url"); if (i) { i.value = url.trim(); document.getElementById("tip-note").focus(); } }, 300);
      if (typeof toast === "function") toast("Link staat klaar bij TIP EEN NIEUWTJE. Zeg er kort bij wat het is en druk op versturen."); }, 1400); });
}

async function weather() {
  try { const r = await fetch("https://api.open-meteo.com/v1/forecast?latitude=52.14&longitude=6.2&current=precipitation,rain,snowfall,weather_code,temperature_2m,is_day&timezone=Europe%2FAmsterdam");
    X.wx = (await r.json()).current; } catch (e) { X.wx = null; }
  applyWeather();
}
function applyWeather() {
  const w = X.wx || {}, rain = (+w.rain || 0) > .05 || [51, 53, 55, 61, 63, 65, 80, 81, 82].includes(+w.weather_code), snow = (+w.snowfall || 0) > 0 || [71, 73, 75, 77, 85, 86].includes(+w.weather_code);
  X.rain.visible = rain && !snow; X.snow.visible = snow;
  if (X.groundMat) { X.groundMat.roughness = rain ? .35 : .95; X.groundMat.metalness = rain ? .25 : 0; }
  X.weatherTxt = w.temperature_2m != null ? `${Math.round(w.temperature_2m)}°C ${snow ? "sneeuw" : rain ? "regen" : "droog"} in Zutphen` : "";
}

// ---------- tandem, publiek, bezorgers ----------
function sendVan(kind) {
  if (X.vans.some(v => v.kind === kind)) return;
  const g = new THREE.Group(), col = kind === "nieuws" ? 0xffffff : 0x1d1d22; scene.add(g);
  mesh(B(2.2, 1.8, 4.4), mat(col, { r: .4 }), 0, 1.25, -.4, g); mesh(B(2.1, 1.1, 1.4), mat(col, { r: .4 }), 0, .95, 2.4, g);
  mesh(B(2.0, .6, .05), mat(0x101820, { m: .8, r: .1 }), 0, 1.25, 3.11, g);
  const sideTex = neonText(kind === "nieuws" ? "NIEUWS BINNEN" : "FOOTAGE", kind === "nieuws" ? "#FF2E88" : "#C6FF00", 6, 1);
  for (const sx of [-1.11, 1.11]) { const pl = plane(sideTex, 3.6, .6, g, sx, 1.5, -.4, sx > 0 ? Math.PI / 2 : -Math.PI / 2); }
  const wg = new THREE.CylinderGeometry(.42, .42, .3, 14); wg.rotateZ(Math.PI / 2);
  for (const [x, z] of [[-1.05, 1.9], [1.05, 1.9], [-1.05, -1.8], [1.05, -1.8]]) mesh(wg, mat(0x0c0c0e), x, .42, z, g);
  const stopX = kind === "nieuws" ? gx("redactie") : gx("jij");
  g.position.set(-48, 0, 1.6); g.rotation.y = Math.PI / 2;
  X.vans.push({ g, kind, stopX, phase: "in", wait: 0 });
}
function stepVans(dt) {
  for (let i = X.vans.length - 1; i >= 0; i--) { const v = X.vans[i];
    if (v.phase === "in") { v.g.position.x += dt * 9 * Math.min(1, (v.stopX - v.g.position.x) / 6 + .15); if (v.g.position.x >= v.stopX - .05) { v.phase = "stop"; v.wait = 4; pop(new THREE.Vector3(v.stopX, 3, 1.6), 20); playPing(660); } }
    else if (v.phase === "stop") { v.wait -= dt; if (v.wait <= 0) v.phase = "uit"; }
    else { v.g.position.x += dt * 12; if (v.g.position.x > 50) { scene.remove(v.g); X.vans.splice(i, 1); } } }
}

// ---------- podium en prestaties ----------
function rankTop3() {
  if (!window.agentLevel) return [];
  return Object.keys(AGENTS).map(id => ({ id, ...agentLevel(id) })).sort((a, b) => b.xp - a.xp).slice(0, 3);
}
function buildPodium() {
  const top = rankTop3(), key = top.map(t => t.id).join(","); if (key === X.podiumKey) return; X.podiumKey = key;
  while (X.podiumFigs.children.length) X.podiumFigs.remove(X.podiumFigs.children[0]);
  top.forEach((t, i) => { const [x, h] = [[0, 1.2], [-1.6, .8], [1.6, .5]][i];
    const f = person(X.podiumFigs, AGENTS[t.id].look, x, 0, t.id, false); f.position.y = h; f.rotation.y = Math.PI; f.userData.cheer = i;
    label(`${AGENTS[t.id].role} <b class="of3-lv">LV ${t.lvl}</b>`, "of3-tag", f, 2.4); });
}
const ACH = [
  ["eerste-post", "Eerste post live", () => stats().posted >= 1],
  ["clips-100", "100 clips klaar", () => (typeof S !== "undefined" && S ? posts().filter(p => /clip|reel/.test(p.kind || "")).length : 0) >= 100],
  ["voorraad-500", "500 op voorraad", () => stats().ready >= 500],
  ["stapel-leeg", "Stapel helemaal leeg", () => stats().rev === 0],
  ["reeks-7", "7 dagen op rij alle opdrachten", () => (LS.get("sw-streak", {}).n || 0) >= 7],
  ["volgers-100", "100 volgers", () => followers() >= 100],
  ["volgers-1000", "1.000 volgers", () => followers() >= 1000],
  ["tip", "Eerste nieuwtje getipt", () => ((typeof TIPS !== "undefined" && TIPS.tips) || []).length >= 1],
  ["level-10", "Een agent op level 10", () => window.agentLevel && Object.keys(AGENTS).some(id => agentLevel(id).lvl >= 10)],
  ["level-25", "Een agent op level 25", () => window.agentLevel && Object.keys(AGENTS).some(id => agentLevel(id).lvl >= 25)],
];
window.officeAchievements = function () {
  const got = LS.get("sw-ach", {});
  for (const [k, , f] of ACH) { try { if (!got[k] && f()) got[k] = todayNL(); } catch (e) {} }
  LS.set("sw-ach", got); return ACH.map(([k, t]) => ({ k, t, at: got[k] || null }));
};
function trophies() {
  const A = officeAchievements().filter(a => a.at), dir = GARAGES[0].group;
  if (X.trophyN === A.length) return; X.trophyN = A.length;
  if (X.trophies) dir.remove(X.trophies); X.trophies = new THREE.Group(); dir.add(X.trophies);
  const gold = mat(0xd4af37, { m: .9, r: .25, e: 0x3a2a00, ei: .4 });
  A.forEach((a, i) => { const y = .5 + (i % 3) * .8, z = .8 + Math.floor(i / 3) * .45;
    mesh(new THREE.CylinderGeometry(.1, .16, .35, 10), gold, -4.95, y + .2, z, X.trophies); mesh(new THREE.SphereGeometry(.14, 10, 8, 0, Math.PI * 2, 0, Math.PI / 2), gold, -4.95, y + .45, z, X.trophies).rotation.x = Math.PI; });
}
// reeks: elke dag dat alle opdrachten gehaald zijn telt mee
window.officeStreak = function () {
  const st = LS.get("sw-streak", { n: 0, last: "" }), d = todayNL(), Q = window.officeQuests ? officeQuests() : [];
  if (Q.length && Q.every(q => q.done) && st.last !== d) { const y = new Date(Date.now() - 864e5).toLocaleDateString("sv-SE", { timeZone: "Europe/Amsterdam" });
    st.n = st.last === y ? st.n + 1 : 1; st.last = d; LS.set("sw-streak", st); }
  const y2 = new Date(Date.now() - 864e5).toLocaleDateString("sv-SE", { timeZone: "Europe/Amsterdam" });
  return st.last === d || st.last === y2 ? st.n : 0;
};

// ---------- de ochtendronde van de hoofdredacteur (08:41) en de strateeg op maandag ----------
function chiefRound() {
  const o = agentObj.hoofdredacteur; if (!o || o.walk) return;
  const seat = new THREE.Vector3(); o.p.getWorldPosition(seat);
  const stops = ["redactie", "pitwall", "jij"].flatMap(g => [[gx(g) - 3, FRONT], [gx(g), GZ + 3.2], [gx(g) + 3, FRONT]]);
  const path = [[seat.x, seat.z + 1.2], [seat.x, FRONT], ...stops].map(([x, z]) => new THREE.Vector3(x, 0, z));
  o.home = { parent: o.p.parent, pos: o.p.position.clone(), rot: o.p.rotation.y }; scene.attach(o.p); pose(o.p, false);
  o.walk = { path, i: 0, phase: "heen", wait: 0, dest: "ronde", back: [...path].reverse().slice(1).concat([seat.clone()]) };
  const b = ((AG.hoofdredacteur || {}).briefing || "").split(/\n/)[0];
  o.say = b ? "Briefing: " + b.slice(0, 40) : "Goedemorgen allemaal, briefing!";
}

// ---------- geluid (standaard uit; alles wordt hier gemaakt, geen geluidsbestanden) ----------
let AC = null, SND = null;
function toggleSound(on) {
  if (on === undefined) on = !SND;
  if (!on) { if (SND) { SND.master.gain.setTargetAtTime(0, AC.currentTime, .1); SND = null; } LS.set("sw-sound", false); return false; }
  AC = AC || new (window.AudioContext || window.webkitAudioContext)(); AC.resume();
  const master = AC.createGain(); master.gain.value = .0; master.connect(AC.destination); master.gain.setTargetAtTime(.5, AC.currentTime, .3);
  const eng = AC.createOscillator(); eng.type = "sawtooth"; const eng2 = AC.createOscillator(); eng2.type = "square";
  const lp = AC.createBiquadFilter(); lp.type = "lowpass"; lp.frequency.value = 500; const eg = AC.createGain(); eg.gain.value = .08;
  eng.connect(lp); eng2.connect(lp); lp.connect(eg); eg.connect(master); eng.start(); eng2.start();
  const buf = AC.createBuffer(1, AC.sampleRate * 2, AC.sampleRate), d = buf.getChannelData(0); for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
  const noise = AC.createBufferSource(); noise.buffer = buf; noise.loop = true; const bp = AC.createBiquadFilter(); bp.type = "bandpass"; bp.frequency.value = 2600; bp.Q.value = 6;
  const ng = AC.createGain(); ng.gain.value = 0; noise.connect(bp); bp.connect(ng); ng.connect(master); noise.start();
  SND = { master, eng, eng2, lp, eg, ng }; LS.set("sw-sound", true); return true;
}
function playPing(f = 880) { if (!SND) return; const o = AC.createOscillator(), g = AC.createGain(); o.frequency.value = f; o.type = "sine"; g.gain.value = .0001;
  o.connect(g); g.connect(SND.master); o.start(); g.gain.exponentialRampToValueAtTime(.25, AC.currentTime + .01); g.gain.exponentialRampToValueAtTime(.0001, AC.currentTime + .35); o.stop(AC.currentTime + .4); }
window.officePing = playPing;

// ---------- tv-modus ----------
let tvTimer = null, tvI = 0;
const TV_TOUR = ["overzicht", "redactie", "pad", "pitwall", "jij", "directie"];
function setTV(on) {
  if (!box) return; if (!on && !box.classList.contains("tv")) return;
  if (!on && location.hash === "#kantoor/tv") history.replaceState(null, "", "#kantoor");
  box.classList.toggle("tv", on); document.body.classList.toggle("tv-on", on);
  let hud = document.getElementById("of3-tvhud");
  if (on) { if (!hud) { hud = document.createElement("div"); hud.id = "of3-tvhud"; box.appendChild(hud); }
    clearInterval(tvTimer); tvI = 0; go(TV_TOUR[0]); tvTimer = setInterval(() => { tvI = (tvI + 1) % TV_TOUR.length; go(TV_TOUR[tvI]); }, 14000);
    try { if (box.requestFullscreen && !document.fullscreenElement) box.requestFullscreen().catch(() => {}); } catch (e) {} }
  else { clearInterval(tvTimer); tvTimer = null; if (hud) hud.remove(); try { if (document.fullscreenElement) document.exitFullscreen(); } catch (e) {} }
  setTimeout(resize, 60); drawTvHud();
}
function drawTvHud() {
  const h = document.getElementById("of3-tvhud"); if (!h) return; const s = stats(), n = NL();
  h.innerHTML = `<img src="assets/woordmerk_kleur.svg" alt=""><div class="tvc">${n.toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit" })}<small>${n.toLocaleDateString("nl-NL", { weekday: "long", day: "numeric", month: "long" })}${X.weatherTxt ? " · " + X.weatherTxt : ""}</small></div>
    <div class="tvk"><span>WACHT OP JOU</span><b style="color:${s.rev ? "#FF2E88" : "#C6FF00"}">${s.rev}</b></div><div class="tvk"><span>VOORRAAD</span><b style="color:#5BC0FF">${s.ready}</b></div>
    <div class="tvk"><span>VOLGERS</span><b>${followers()}</b></div><div class="tvk"><span>REEKS</span><b style="color:#FF9F43">${window.officeStreak ? officeStreak() : 0}</b></div>
    <button onclick="office3d.tv(false)">SLUITEN</button>`;
}
document.addEventListener("keydown", e => { if (e.key === "Escape" && box && box.classList.contains("tv")) setTV(false); });
document.addEventListener("fullscreenchange", () => { if (!document.fullscreenElement && box && box.classList.contains("tv")) setTV(false); });

// ---------- per statusronde ----------
function extrasState(night) {
  const s = stats(), F = followers(), month = NL().getMonth();
  // groei van het terrein
  const lvl = F >= 100000 ? 3 : F >= 10000 ? 2 : F >= 1000 ? 1 : 0; X.grow.forEach((g, i) => g.visible = lvl > i);
  // event-dag: de Mac verwerkt een stream of het is een raceweekend: vol publiek
  X.event = !!fx.macBusy; X.crowd.forEach(c => { if (c.userData.keep !== undefined) c.visible = X.event || c.userData.keep; });
  // december
  X.xmas.visible = month === 11;
  if (month === 11 && !X.wx?.snowfall && X.snow) X.snow.visible = X.snow.visible || (NL().getDate() >= 20);
  // waarschuwingen: post binnen 30 minuten live, of een kanaal niet verbonden
  const P = (typeof S !== "undefined" && S) ? posts() : [], soon = P.some(p => p.post_at && ["ready", "approved"].includes(p.status) && new Date(p.post_at) - Date.now() < 30 * 60e3 && new Date(p.post_at) > Date.now());
  X.soon = soon; const ch = ((typeof S !== "undefined" && S && S.channels && S.channels.channels) || []).filter(c => c.id !== "telegram");
  X.trouble = ch.some(c => !c.connected) || Object.values(typeof AG !== "undefined" ? AG : {}).some(a => a.state === "fout");
  buildPodium(); trophies(); if (window.officeStreak) officeStreak(); drawTvHud();
  // ochtendronde: elke dag tussen 08:41 en 09:15
  const n = NL(), mins = n.getHours() * 60 + n.getMinutes(), d = todayNL();
  if (mins >= 8 * 60 + 41 && mins <= 9 * 60 + 15 && LS.get("sw-round") !== d) { LS.set("sw-round", d); chiefRound(); }
  // bezorgers: nieuwe nieuwtjes van de scout, nieuwe footage voor de Mac
  const inbox = ((typeof S !== "undefined" && S && S.inbox) || []).length; if (X.lastInbox != null && inbox > X.lastInbox) sendVan("nieuws"); X.lastInbox = inbox;
  if (fx.macBusy && !X.lastMac) sendVan("footage"); X.lastMac = fx.macBusy;
}

// ---------- per frame ----------
function extrasTick(dt, t) {
  // jij typt
  if (X.me) { const u = X.me.userData; u.arms[0].rotation.x = 1.1 + Math.sin(t * 14) * .08; u.arms[1].rotation.x = 1.1 + Math.cos(t * 14) * .08; u.head.rotation.y = Math.sin(t * .5) * .2; }
  // tandem: de tweede auto volgt de eerste
  if (X.car2 && fx.car) { const a = t * .9 - .62, rx = 7, rz = 4.5; X.car2.position.set(Math.cos(a) * rx, 0, 12 + Math.sin(a) * rz);
    X.car2.rotation.y = Math.atan2(-Math.sin(a) * rx, Math.cos(a) * rz) + .78; X.car2.userData.wheels.forEach(w => w.rotation.x += dt * 25);
    if (Math.random() < .35) { const sm = fx.smoke.find(s => s.userData.life <= 0); if (sm) { sm.position.copy(new THREE.Vector3(Math.random() - .5, .4, -1.9).applyMatrix4(X.car2.matrixWorld)); sm.userData.life = 1; sm.scale.setScalar(.6); } } }
  // publiek springt als de auto's langskomen
  for (const c of X.crowd) if (c.visible) { const near = fx.car ? Math.max(0, 1 - Math.abs(c.getWorldPosition(new THREE.Vector3()).x - fx.car.position.x) / 10) : 0;
    c.position.y = (c.userData.base ??= c.position.y) + Math.max(0, Math.sin(t * 8 + c.userData.ph)) * (.08 + near * .35 * (X.event ? 1 : .3)); }
  // podium juicht
  if (X.podiumFigs) X.podiumFigs.children.forEach((f, i) => { const u = f.userData; if (!u.arms) return; const up = Math.sin(t * 5 + i) > 0; u.arms[0].rotation.x = u.arms[1].rotation.x = up ? 3 : 2.4; });
  stepVans(dt);
  // waarschuwingslamp draait als er zo een post live gaat; rook bij de server bij een probleem
  if (X.beacon) { const on = X.soon || X.keyBeacon, col = X.keyBeacon ? 0xff2020 : 0xff7a00; X.beacon.rotation.y += dt * 5;
    X.beacon.children[0].material.emissive.setHex(col); X.beacon.children[0].material.emissiveIntensity = on ? 3 : 0; X.beaconLight.color.setHex(col); X.beaconLight.intensity = on ? 60 : 0; }
  if (X.trouble && Math.random() < .5) { const sp = X.smoke.find(s => s.userData.life <= 0); if (sp) { sp.position.set(gx("jij") + 3.6 + (Math.random() - .5) * .6, 2.7, -9.6); sp.userData.life = 1; sp.scale.setScalar(.5); } }
  for (const sp of X.smoke) if (sp.userData.life > 0) { sp.userData.life -= dt * .35; sp.position.y += dt * .9; sp.scale.multiplyScalar(1 + dt); sp.material.opacity = Math.max(0, sp.userData.life) * .6; }
  // neerslag
  for (const P of [X.rain, X.snow]) if (P && P.visible) { const a = P.geometry.attributes.position.array, fall = P === X.rain ? 22 : 1.6;
    for (let i = 1; i < a.length; i += 3) { a[i] -= fall * dt; if (P === X.snow) a[i - 1] += Math.sin(t + i) * dt * .3; if (a[i] < 0) a[i] = 25; } P.geometry.attributes.position.needsUpdate = true; }
  // geluid: motor en banden, harder als de camera dicht bij het pad is
  if (SND) { const dist = camera.position.distanceTo(fx.car.position), vol = Math.max(.05, 1 - dist / 60), rev = 70 + (Math.sin(t * 1.7) + 1) * 30;
    SND.eng.frequency.setTargetAtTime(rev, AC.currentTime, .05); SND.eng2.frequency.setTargetAtTime(rev * 1.5, AC.currentTime, .05);
    SND.eg.gain.setTargetAtTime(.09 * vol, AC.currentTime, .1); SND.ng.gain.setTargetAtTime((.02 + Math.max(0, Math.sin(t * 1.3)) * .05) * vol, AC.currentTime, .1); }
  // tv: langzaam meedraaien
  if (box.classList.contains("tv") && !camGoal) { const r = camera.position.clone().sub(controls.target); r.applyAxisAngle(new THREE.Vector3(0, 1, 0), dt * .05); camera.position.copy(controls.target).add(r); }
}

// =====================================================================================
// RONDE 4: blussen bij een fout, gezichten in het schermlicht, rijders op de tandemauto's,
// plassen bij regen, praatjes, de strateeg bij het whiteboard, jij die even weg loopt,
// en een feestje als er een post live gaat.
// =====================================================================================
const R4 = { puddles: [], ext: {}, foam: [], lastPosted: null, idleSince: Date.now(), meAway: false, banners: [] };

function r4Build() {
  // gezichten krijgen het licht van het scherm
  for (const [id, o] of Object.entries(agentObj)) o.p.traverse(m => { if (m.isMesh && m.geometry.type === "SphereGeometry" && m.geometry.parameters.radius === .24) o.face = m; });
  // plassen (alleen zichtbaar bij regen)
  const pm = new THREE.MeshStandardMaterial({ color: 0x0b0c10, roughness: .04, metalness: .9 });
  for (let i = 0; i < 14; i++) { const r = .8 + Math.random() * 1.8, m = new THREE.Mesh(new THREE.CircleGeometry(r, 20), pm); m.rotation.x = -Math.PI / 2; m.scale.y = .6 + Math.random() * .4;
    m.position.set((Math.random() - .5) * 50, .015, 2 + Math.random() * 20); m.visible = false; scene.add(m); R4.puddles.push(m); }
  // brandblussers aan de muur bij de serverkast
  const sx = gx("jij") + 2.4;
  R4.extRack = mesh(new THREE.CylinderGeometry(.14, .14, .6, 12), mat(0xd01818, { r: .3 }), sx, .9, -10.2, scene);
  // namen van rijders op de voorruit van de tandemauto's
  for (const car of [fx.car, X.car2]) { const t = canvasTex(512, 96, () => {}); const pl = plane(t, 1.5, .28, car, 0, 1.33, .82, 0); pl.rotation.x = -1.0; R4.banners.push(t); }
  // jij: activiteit bijhouden
  ["pointerdown", "keydown", "wheel"].forEach(ev => window.addEventListener(ev, () => { R4.idleSince = Date.now(); }, { passive: true }));
  // schuimdeeltjes
  const ft = canvasTex(64, 64, (g) => { const gr = g.createRadialGradient(32, 32, 2, 32, 32, 32); gr.addColorStop(0, "rgba(255,255,255,.9)"); gr.addColorStop(1, "rgba(255,255,255,0)"); g.fillStyle = gr; g.fillRect(0, 0, 64, 64); });
  for (let i = 0; i < 40; i++) { const sp = new THREE.Sprite(new THREE.SpriteMaterial({ map: ft, transparent: true, depthWrite: false, opacity: 0 })); sp.userData.life = 0; scene.add(sp); R4.foam.push(sp); }
}

function topDrivers() {
  const P = (typeof S !== "undefined" && S) ? posts() : [], c = {};
  for (const p of P) for (const n of (p.people || [])) if (n && n.length < 30) c[n] = (c[n] || 0) + 1;
  return Object.entries(c).sort((a, b) => b[1] - a[1]).map(x => x[0]).slice(0, 2);
}
function r4State() {
  // rijders op de tandemauto's: de twee namen die het vaakst in je posts staan
  R4.puddles.forEach(p => p.visible = !!(X.rain && X.rain.visible));
  // gezichten
  for (const o of Object.values(agentObj)) if (o.face) { o.face.material.emissive.setHex(o.st === "bezig" ? LIME : o.st === "fout" ? PINK : 0x000000); o.face.material.emissiveIntensity = o.st === "bezig" ? .12 : .18; }
  // post live gegaan sinds de vorige keer: feestje
  const posted = stats().posted; if (R4.lastPosted != null && posted > R4.lastPosted) liveMoment(); R4.lastPosted = posted;
  // strateeg op maandag tussen 07:47 en 08:30 bij het whiteboard
  const n = NL(), mins = n.getHours() * 60 + n.getMinutes(), d = todayNL();
  if (n.getDay() === 1 && mins >= 7 * 60 + 47 && mins <= 8 * 60 + 30 && LS.get("sw-plan") !== d) { LS.set("sw-plan", d); strategistBoard(); }
}

function walkTo(id, pts, wait, say, onArrive) {
  const o = agentObj[id]; if (!o || o.walk) return;
  const seat = new THREE.Vector3(); o.p.getWorldPosition(seat);
  const path = [[seat.x, seat.z + 1.2], ...pts].map(([x, z]) => new THREE.Vector3(x, 0, z));
  o.home = { parent: o.p.parent, pos: o.p.position.clone(), rot: o.p.rotation.y }; scene.attach(o.p); pose(o.p, false);
  o.walk = { path, i: 0, phase: "heen", wait: 0, dest: "custom", waitFor: wait, onArrive, back: [...path].reverse().slice(1).concat([seat.clone()]) };
  o.say = say;
}
function strategistBoard() {
  const x = gx("directie") - .6; walkTo("strateeg", [[x, GZ - 2.2]], 12, "nieuw weekplan hangt op het bord", () => redraw(boards.plan, drawPlanBoard));
}
function liveMoment() {
  fireworks(); playPing(523); setTimeout(() => playPing(659), 140); setTimeout(() => playPing(784), 280);
  R4.liveFlash = 6;
  for (const id of ["battle", "podcast", "nieuws", "community"]) { const o = agentObj[id]; if (o) o.say = "WE ZIJN LIVE! 🎉"; }
  setTimeout(() => { for (const id of ["battle", "podcast", "nieuws", "community"]) { const o = agentObj[id]; if (o && o.say === "WE ZIJN LIVE! 🎉") o.say = null; } }, 7000);
}

const CHAT = [["Zag je die tandem van gisteren?", "Bizar dichtbij!"], ["Hoeveel clips heb jij al?", "Genoeg voor de hele maand"], ["Koffie?", "Altijd"],
  ["Wie wint FD volgend jaar?", "Geen idee, maar het wordt spannend"], ["Drift Masters battles komen eraan", "Eindelijk!"], ["Die caption was goed", "Dank je, Joshua keurde hem meteen goed"]];

function r4Tick(dt, t) {
  // stappen in een eigen wandeling (walkTo): wachten en terug
  for (const [id, o] of Object.entries(agentObj)) { const W = o.walk; if (!W || W.dest !== "custom") continue;
    if (W.phase === "heen" && W.i >= W.path.length && W.wait <= 0 && !W.arrived) { W.arrived = true; W.wait = W.waitFor; if (W.onArrive) W.onArrive(); } }
  // fout: pak de blusser, ren naar de serverkast, blus, en terug
  for (const [id, o] of Object.entries(agentObj)) {
    if (o.st === "fout" && !o.walk && !AGENTS[id].stand && !(R4.ext[id] > t)) { R4.ext[id] = t + 30;
      const x = gx("jij"); walkTo(id, [[x - 3, FRONT], [x + 2.4, GZ - 3.4], [x + 3.2, GZ - 2.4]], 6, "BLUSSEN! 🧯", () => { o.extinguish = 6; });
      if (o.walk) { const ex = new THREE.Group(); mesh(new THREE.CylinderGeometry(.11, .11, .45, 10), mat(0xd01818, { r: .3 }), 0, -.55, -.1, ex); o.p.userData.arms[1].add(ex); o.extObj = ex; } }
    if (o.extinguish > 0) { o.extinguish -= dt; const u = o.p.userData; u.arms[1].rotation.x = 1.4; u.arms[0].rotation.x = 1.2;
      if (Math.random() < .8) { const f = R4.foam.find(f => f.userData.life <= 0); if (f) { const a = new THREE.Vector3(); o.p.getWorldPosition(a); f.position.set(a.x + .3, 1.2, a.z - .6); f.userData.v = new THREE.Vector3(.6 + Math.random(), Math.random() * .6, -1.6 - Math.random()); f.userData.life = 1; f.scale.setScalar(.3); } }
      if (o.extinguish <= 0 && o.extObj) { o.p.userData.arms[1].remove(o.extObj); o.extObj = null; } }
  }
  for (const f of R4.foam) if (f.userData.life > 0) { f.userData.life -= dt * .9; f.position.addScaledVector(f.userData.v, dt); f.scale.multiplyScalar(1 + dt * 1.5); f.material.opacity = Math.max(0, f.userData.life) * .8; }
  // praatjes: twee lopers dicht bij elkaar
  const walkers = Object.values(agentObj).filter(o => o.walk && !o.extinguish);
  for (let i = 0; i < walkers.length; i++) for (let j = i + 1; j < walkers.length; j++) { const a = walkers[i], b = walkers[j];
    if (a.p.position.distanceTo(b.p.position) < 2.2 && !(a.chatUntil > t)) { const c = CHAT[Math.floor(Math.random() * CHAT.length)];
      a.say = c[0]; b.say = null; a.chatUntil = b.chatUntil = t + 6; setTimeout(() => { b.say = c[1]; }, 1800); } }
  // jij: na 3 minuten zonder klikken loop je even naar het pad, bij een klik ben je terug
  if (X.me) { const idle = Date.now() - R4.idleSince > 180e3, u = X.me.userData;
    if (idle && !R4.meAway) { R4.meAway = true; R4.meHome = { parent: X.me.parent, pos: X.me.position.clone(), rot: X.me.rotation.y }; scene.attach(X.me); pose(X.me, false); R4.meT = 0; }
    if (R4.meAway) { R4.meT += dt; const target = idle ? new THREE.Vector3(gx("jij") - 6, 0, 5.5) : (() => { const v = new THREE.Vector3(); R4.meHome.parent.localToWorld(v.copy(R4.meHome.pos)); return v; })();
      const d = target.clone().sub(X.me.position); d.y = 0; const dist = d.length();
      if (dist > .1) { X.me.position.add(d.multiplyScalar(Math.min(1, 2.2 * dt / dist))); X.me.rotation.y = Math.atan2(-(target.x - X.me.position.x), -(target.z - X.me.position.z));
        u.legs[0].rotation.x = Math.sin(t * 9) * .6; u.legs[1].rotation.x = -Math.sin(t * 9) * .6; }
      else { u.legs.forEach(l => l.rotation.x = 0); if (idle) X.me.rotation.y = Math.PI * 1.15;
        else { R4.meHome.parent.attach(X.me); X.me.position.copy(R4.meHome.pos); X.me.rotation.set(0, R4.meHome.rot, 0); pose(X.me, true); R4.meAway = false; } } } }
  // live: het led-bord knippert
  if (R4.liveFlash > 0) { R4.liveFlash -= dt; if (boards.bill && Math.floor(t * 4) % 2 === 0) redraw(boards.bill, (g, w, h) => { g.fillStyle = "#C6FF00"; g.fillRect(0, 0, w, h); g.fillStyle = "#111";
      g.font = "italic 900 200px 'Bebas Neue',Impact,sans-serif"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText("NU LIVE!", w / 2, h / 2 + 10); }); else if (boards.bill) redraw(boards.bill, drawBillboard);
    if (R4.liveFlash <= 0 && boards.bill) redraw(boards.bill, drawBillboard); }
}

// =====================================================================================
// RONDE 5: rijders op de auto's (naam, startnummer en landvlag uit data/sources.csv, in de
// kleuren van Sideways Wire; geen nagemaakte livery's of sponsorlogo's) en sleutels die verlopen.
// =====================================================================================
const FLAGS = {
  "Ierland": ["v", "#169B62", "#ffffff", "#FF883E"], "Italië": ["v", "#009246", "#ffffff", "#CE2B37"], "Frankrijk": ["v", "#0055A4", "#ffffff", "#EF4135"],
  "Polen": ["h", "#ffffff", "#DC143C"], "Nederland": ["h", "#AE1C28", "#ffffff", "#21468B"], "Estland": ["h", "#0072CE", "#000000", "#ffffff"],
  "Litouwen": ["h", "#FDB913", "#006A44", "#C1272D"], "Letland": ["h", "#9E3039", "#ffffff", "#9E3039"], "Hongarije": ["h", "#CE2939", "#ffffff", "#477050"],
  "Oekraïne": ["h", "#0057B7", "#FFD700"], "Egypte": ["h", "#CE1126", "#ffffff", "#000000"], "El Salvador": ["h", "#0F47AF", "#ffffff", "#0F47AF"],
  "Portugal": ["v2", "#006600", "#FF0000"], "Brazilië": ["h", "#009C3B", "#FFDF00", "#009C3B"], "Australië": ["h", "#012169", "#012169"],
  "Turkije": ["h", "#E30A17", "#E30A17"], "Israël": ["h", "#ffffff", "#0038b8", "#ffffff"], "Cyprus": ["h", "#ffffff", "#ffffff"], "Tsjechië": ["h", "#ffffff", "#D7141A"],
  "Finland": ["x", "#ffffff", "#003580"], "Noorwegen": ["x", "#BA0C2F", "#00205B", "#ffffff"], "Zwitserland": ["c", "#DA291C", "#ffffff"], "Japan": ["j", "#ffffff", "#BC002D"],
};
function drawFlag(g, w, h, land) {
  const f = FLAGS[land]; if (!f) { g.fillStyle = "#C6FF00"; g.fillRect(0, 0, w, h); g.fillStyle = "#FF2E88"; g.fillRect(0, h * .4, w, h * .2); return; }
  const [t, ...c] = f;
  if (t === "v") c.forEach((col, i) => { g.fillStyle = col; g.fillRect(i * w / c.length, 0, w / c.length + 1, h); });
  else if (t === "v2") { g.fillStyle = c[0]; g.fillRect(0, 0, w * .4, h); g.fillStyle = c[1]; g.fillRect(w * .4, 0, w * .6, h); }
  else if (t === "h") c.forEach((col, i) => { g.fillStyle = col; g.fillRect(0, i * h / c.length, w, h / c.length + 1); });
  else if (t === "x") { g.fillStyle = c[0]; g.fillRect(0, 0, w, h); if (c[2]) { g.fillStyle = c[2]; g.fillRect(w * .28, 0, w * .2, h); g.fillRect(0, h * .38, w, h * .24); }
    g.fillStyle = c[1]; g.fillRect(w * .32, 0, w * .12, h); g.fillRect(0, h * .43, w, h * .14); }
  else if (t === "c") { g.fillStyle = c[0]; g.fillRect(0, 0, w, h); g.fillStyle = c[1]; g.fillRect(w * .43, h * .2, w * .14, h * .6); g.fillRect(w * .3, h * .43, w * .4, h * .14); }
  else if (t === "j") { g.fillStyle = c[0]; g.fillRect(0, 0, w, h); g.fillStyle = c[1]; g.beginPath(); g.arc(w / 2, h / 2, h * .3, 0, 7); g.fill(); }
}
const PAINT = [PINK, LIME, BLUE, ORANGE, 0xf2f2f2, 0x1d1d22];
function driverFor(name) {
  const D = (typeof S !== "undefined" && S && S.drivers) || [], low = String(name || "").toLowerCase();
  return D.find(d => d.name.toLowerCase() === low) || D.find(d => (d.aliases || "").toLowerCase().split(/[;,]/).map(x => x.trim()).includes(low))
    || D.find(d => low && (d.name.toLowerCase().includes(low) || low.includes(d.name.toLowerCase().split(" ").pop())));
}
function decals(car) {
  if (car.userData.dec) return car.userData.dec;
  const num = canvasTex(256, 256, () => {}), flag = canvasTex(192, 128, () => {});
  const dec = { num, flag };
  for (const sx of [-1, 1]) { const p = plane(num, .78, .78, car, sx * .965, .62, .25, sx * Math.PI / 2); p.renderOrder = 2; }
  const roof = plane(num, .9, .9, car, 0, 1.335, -.3, 0); roof.rotation.x = -Math.PI / 2;
  const hood = plane(flag, .9, .6, car, 0, .785, 1.45, 0); hood.rotation.x = -Math.PI / 2;
  car.userData.dec = dec; return dec;
}
function paintCar(car, d, color) {
  if (!car) return;
  const key = (d ? d.name : "-") + color; if (car.userData.liveryKey === key) return; car.userData.liveryKey = key;
  car.userData.paint.color.setHex(color);
  const light = [LIME, 0xf2f2f2, ORANGE].includes(color), dec = decals(car);
  redraw(dec.num, (g, w, h) => { g.clearRect(0, 0, w, h); g.fillStyle = "#ffffff"; g.beginPath(); g.arc(w / 2, h / 2, w * .46, 0, 7); g.fill();
    g.lineWidth = 10; g.strokeStyle = light ? "#111" : "#C6FF00"; g.stroke(); g.fillStyle = "#111"; g.textAlign = "center"; g.textBaseline = "middle";
    const n = d ? d.nr : "SW"; g.font = `italic 900 ${n.length > 2 ? 110 : 140}px 'Bebas Neue',Impact,sans-serif`; g.fillText(n, w / 2, h / 2 + 8); });
  redraw(dec.flag, (g, w, h) => drawFlag(g, w, h, d && d.land));
  car.userData.driver = d ? d.name : null;
}
function liveries() {
  const D = (typeof S !== "undefined" && S && S.drivers) || []; if (!D.length) return;
  const top = topDrivers().map(driverFor).filter(Boolean);
  const day = +todayNL().replaceAll("-", ""), prio1 = D.filter(d => d.prio === "1" && !top.includes(d));
  const pick = i => top[i] || prio1[(day + i * 7) % Math.max(1, prio1.length)];
  paintCar(fx.car, pick(0), 0xf2f2f2); paintCar(X.car2, pick(1), LIME);
  paintCar(fx.liftCar, prio1[(day + 3) % Math.max(1, prio1.length)], PINK);
  // namen op de voorruit volgen de echte bestuurders
  const names = [fx.car, X.car2].map(c => c && c.userData.driver);
  R4.banners.forEach((t, i) => redraw(t, (g, w, h) => { g.fillStyle = i ? "#C6FF00" : "#111"; g.fillRect(0, 0, w, h); g.font = "italic 900 60px 'Bebas Neue',Impact,sans-serif";
    g.fillStyle = i ? "#111" : "#C6FF00"; g.textAlign = "center"; g.textBaseline = "middle"; g.fillText(String(names[i] || "SIDEWAYS WIRE").toUpperCase().slice(0, 18), w / 2, h / 2 + 3); }));
}
window.officeCars = () => [fx.car, X.car2, fx.liftCar].map(c => c && c.userData.driver).filter(Boolean);

// sleutels: rook en rood zwaailicht als er een verloopt (binnen 7 dagen) of niet werkt
window.officeKeys = function () {
  const K = ((typeof S !== "undefined" && S && S.keys && S.keys.keys) || {}), out = Object.values(K).map(k => ({ ...k }));
  try { const exp = localStorage.getItem("sw_gh_key_exp"); if (exp) { const days = (new Date(exp + "T23:59:59") - Date.now()) / 864e5;
    out.push({ name: "Dashboard-sleutel (deze browser)", expires: exp, days_left: Math.round(days * 10) / 10, state: days < 0 ? "verlopen" : days < 7 ? "verloopt bijna" : "ok" }); } } catch (e) {}
  return out;
};
function keyTrouble() {
  const bad = officeKeys().filter(k => ["verlopen", "werkt niet", "verloopt bijna"].includes(k.state));
  X.keyBad = bad; if (bad.length) X.trouble = true;
  if (X.beacon) X.keyBeacon = bad.length > 0;
}

// =====================================================================================
// RONDE 6: kant-en-klare modellen (Kenney, MIT-licentie, zie docs/models/README.md) rond het
// terrein, en echte schaduwen van de garagelampen en lichtmasten 's nachts (alleen op een
// computer; op een telefoon blijft het licht en snel).
// =====================================================================================
const R6 = { hq: !(matchMedia("(pointer: coarse)").matches || innerWidth < 800), nightLights: [], loaded: false };
function place(url, x, y, z, ry = 0, size = null, onLoad) {
  new GLTFLoader().load(url, g => { const o = g.scene;
    if (size) { const b = new THREE.Box3().setFromObject(o), sz = b.getSize(new THREE.Vector3()); o.scale.setScalar(size / Math.max(sz.x, sz.z)); }
    o.position.set(x, y, z); o.rotation.y = ry;
    o.traverse(m => { if (m.isMesh) { m.castShadow = true; m.receiveShadow = true; } });
    scene.add(o); if (onLoad) onLoad(o); }, undefined, () => {});
}
function r6Build() {
  const R = "models/racing/", C = "models/city/";
  // start/finish-boog bij de ingang, met het neonbord erop
  // de boog staat over de toegangsweg: de bezorgbusjes rijden er onderdoor
  place(R + "track-finish.glb", -34, 0, 1.6, Math.PI / 2, 9, o => { const b = new THREE.Box3().setFromObject(o);
    const t = plane(neonText("SIDEWAYS WIRE", "#C6FF00", 8, 1), 6, .75, scene, b.max.x + .05, b.max.y - .9, 1.6, Math.PI / 2); });
  // paddock: tenten en pickups van de teams aan beide kanten
  place(R + "decoration-tents.glb", -38, 0, 4, Math.PI / 2, 10);
  place(R + "track-tents.glb", 38, 0, 4, -Math.PI / 2, 10);
  const trucks = ["red", "green", "yellow", "purple"];
  [[-36, 13, .4], [-39, 16, .9], [36, 13, -.4], [39, 16, -.9]].forEach(([x, z, r], i) => place(R + `vehicle-truck-${trucks[i]}.glb`, x, 0, z, r, 3.2));
  // achtergrond: bos achter de garages en een stukje stad
  for (const x of [-40, -30, -20, -10, 0, 10, 20, 30, 40]) place(R + "decoration-forest.glb", x, 0, -17, (x / 10) % 2 ? 0 : Math.PI, 10);
  ["a", "b", "c", "d", "a", "c"].forEach((k, i) => place(C + `building-small-${k}.glb`, -30 + i * 12, 0, -28 - (i % 2) * 4, 0, 7));
  for (const [x, z] of [[-44, 22], [44, 22], [-44, -6], [44, -6]]) place(C + "grass-trees-tall.glb", x, 0, z, 0, 6);
  // schaduwen 's nachts: een spot per garage en de twee lichtmasten
  if (R6.hq) {
    renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    for (const G of GARAGES) { const sp = new THREE.SpotLight(0xfff2e0, 0, 16, 1.0, .6, 1.2); sp.position.set(0, WALL_H - .2, 1.2); sp.target.position.set(0, 0, -.5);
      sp.castShadow = true; sp.shadow.mapSize.set(1024, 1024); sp.shadow.bias = -.0008; sp.shadow.camera.near = .5; sp.shadow.camera.far = 16;
      G.group.add(sp, sp.target); R6.nightLights.push(sp); }
  }
}
function r6State(night) {
  // overdag geeft de zon de schaduwen; 's nachts de lampen
  R6.nightLights.forEach(l => { l.intensity = night ? 160 : 0; l.castShadow = night; });
  if (fx.sun) fx.sun.castShadow = !night || !R6.hq;
}
