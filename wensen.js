// Zoekwens-alarm voor Slim zoeken.
// Draait na de dagelijkse update. Kijkt of nieuwe auto's passen bij een zoekwens uit zoekwensen.txt
// en maakt dan een melding (GitHub-issue) aan, zodat je een e-mail krijgt.
const fs = require("fs");

const MELDEN_AAN = "TomKreling"; // GitHub-gebruikersnaam die de melding krijgt (laat leeg voor geen toewijzing)

function laadZoekmachine() {
  const html = fs.readFileSync("index.html", "utf8");
  const parts = html.split("<script>");
  let js = parts[parts.length - 1].split("</script>")[0];
  js = js.split("function run()")[0].replace("let filters=null", "var filters0=null").replace(/let PHOTOS=\{\};\nfetch[^\n]*\n/, "");
  global.window = {};
  global.localStorage = { getItem: () => null, setItem: () => {}, removeItem: () => {} };
  global.location = { search: "", href: "", origin: "", pathname: "" };
  // eslint-disable-next-line no-eval
  const Z = eval(js + "\n;({localParse, checks, CARS, fmtEUR, fmtKm})");
  Z.cleanUitv = s => (s || "").split(/\s(?:Navigatie|Camera|Trekhaak|LED|Panoramadak|Stoelverwarming|Climate|Cruise|Parkeersensoren|DAB|App-Connect|Virtual)\b/)[0];
  return Z;
}

function leesWensen() {
  if (!fs.existsSync("zoekwensen.txt")) return [];
  return fs.readFileSync("zoekwensen.txt", "utf8").split(/\r?\n/)
    .map(r => r.trim()).filter(r => r && !r.startsWith("#"))
    .map(r => { const d = r.split("|").map(x => x.trim()); return d.length >= 3 ? { naam: d[0], contact: d[1], wens: d.slice(2).join(" | ") } : (d.length === 1 ? { naam: "", contact: "", wens: d[0] } : null); })
    .filter(Boolean);
}

async function melding(titel, tekst) {
  const repo = process.env.GITHUB_REPOSITORY, token = process.env.GITHUB_TOKEN;
  if (!repo || !token) { console.log("(geen GitHub-token, melding alleen in het log)\n" + titel + "\n" + tekst); return; }
  const body = { title: titel, body: tekst, labels: ["zoekwens"] };
  if (MELDEN_AAN) body.assignees = [MELDEN_AAN];
  const r = await fetch(`https://api.github.com/repos/${repo}/issues`, {
    method: "POST", headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json", "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) {
    // nog een keer zonder toewijzing (bijv. als de gebruikersnaam niet klopt)
    delete body.assignees;
    const r2 = await fetch(`https://api.github.com/repos/${repo}/issues`, {
      method: "POST", headers: { Authorization: "Bearer " + token, Accept: "application/vnd.github+json", "Content-Type": "application/json" }, body: JSON.stringify(body) });
    console.log(r2.ok ? "Melding gemaakt (zonder toewijzing): " + titel : "Melding mislukt: " + r2.status + " " + (await r2.text()));
  } else console.log("Melding gemaakt: " + titel);
}

(async () => {
  let nieuw = [];
  try { nieuw = JSON.parse(fs.readFileSync("nieuw.json", "utf8")); } catch (e) { console.log("Geen nieuwe auto's om te controleren."); return; }
  if (!nieuw.length) { console.log("Geen nieuwe auto's binnengekomen."); return; }
  const wensen = leesWensen();
  if (!wensen.length) { console.log("Geen zoekwensen in zoekwensen.txt."); return; }
  const Z = laadZoekmachine();
  const auto = Z.CARS.filter(c => nieuw.includes(c[0]));
  let n = 0;
  for (const w of wensen) {
    const f = Z.localParse(w.wens);
    const exact = [], bijna = [];
    for (const c of auto) {
      const fails = Z.checks(c, f).filter(x => !x.ok);
      if (!fails.length) exact.push(c); else if (fails.length === 1 && fails[0].near) bijna.push([c, fails[0].why]);
    }
    if (!exact.length && !bijna.length) continue;
    const regel = c => `- **${c[1]} ${Z.cleanUitv(c[2])}** · ${Z.fmtEUR(c[3])} · ${c[5]} · ${Z.fmtKm(c[7])}\n  https://janvanveenautos.nl/occasions-kopen/${c[0]}`;
    let tekst = `**Zoekwens:** ${w.wens}\n**Klant:** ${w.naam || "-"} ${w.contact ? "(" + w.contact + ")" : ""}\n`;
    if (exact.length) tekst += `\n### Past precies (${exact.length})\n` + exact.map(regel).join("\n") + "\n";
    if (bijna.length) tekst += `\n### Past bijna (${bijna.length})\n` + bijna.map(([c, why]) => regel(c) + `\n  _mist: ${why}_`).join("\n") + "\n";
    const eerste = exact[0] || bijna[0][0];
    const tel = (w.contact || "").replace(/[^\d+]/g, "");
    if (tel.length >= 9) {
      const nr = tel.startsWith("+") ? tel.slice(1) : tel.startsWith("0") ? "31" + tel.slice(1) : tel;
      const lijst = (exact.length ? exact : [eerste]).slice(0, 3).map(c => `${c[1]} ${Z.cleanUitv(c[2])} voor ${Z.fmtEUR(c[3])}: https://janvanveenautos.nl/occasions-kopen/${c[0]}`).join("\n");
      const bericht = `Hallo ${w.naam || ""}, er is net iets binnengekomen dat past bij je zoekwens (${w.wens}):\n${lijst}\n\nGroet, Jan van Veen Auto's`;
      tekst += `\n[Stuur de klant direct een WhatsApp](https://wa.me/${nr}?text=${encodeURIComponent(bericht)})\n`;
    }
    tekst += "\nZet de wens uit zoekwensen.txt (of zet er # voor) als de klant geholpen is.";
    const titel = `${exact.length ? "Zoekwens-match" : "Bijna-match"}: ${w.naam || w.wens} – ${exact.length || bijna.length} nieuwe auto${(exact.length || bijna.length) === 1 ? "" : "'s"}`;
    await melding(titel, tekst);
    n++;
  }
  console.log(`Zoekwens-alarm: ${wensen.length} wensen, ${auto.length} nieuwe auto's, ${n} meldingen.`);
})();
