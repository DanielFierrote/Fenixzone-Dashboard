import json, os, re, sys, unicodedata
from collections import Counter

BASE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(BASE, "asistente_log.jsonl")
VOTOS = os.path.join(BASE, "asistente_votos.jsonl")
TOP  = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 30
UMBRAL = 0.5

STOP = set("a al algo como con cual cuales cuando de del el ella ellos en entre es esta estan este esto fue ha hay la las le les lo los me mi mis mas muy no nos o para pero por que se si sin sobre su sus te tu tus un una uno unos unas y ya yo quiero puedo puede pueden hacer hago donde cuanto son ser soy hola gracias favor porque".split())
NO_DATO = ("no tengo", "no sé", "no se ", "no está en", "no esta en", "foro o a un admin", "foro o un admin", "no tengo ese dato",
           "no puedo ayudar", "solo ayudo", "no está disponible", "no pude")

def toks(t):
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    out = set()
    for w in re.findall(r"[a-z0-9]+", t):
        if w in STOP or len(w) < 2: continue
        if len(w) > 4 and w.endswith("es"): w = w[:-2]
        elif len(w) > 3 and w.endswith("s"): w = w[:-1]
        out.add(w)
    return out

def parecido(a, b):
    return len(a & b) / len(a | b) if a and b else 0.0

def leer_votos(regs):
    if not os.path.exists(VOTOS):
        return []
    ultimo = {}
    with open(VOTOS, encoding="utf-8") as f:
        for linea in f:
            try:
                v = json.loads(linea); ultimo[(v["i"], v.get("u"))] = v["v"]
            except Exception:
                pass
    por_id = {r["i"]: r for r in regs if r.get("i")}
    cuenta = {}
    for (rid, _), voto in ultimo.items():
        if rid in por_id:
            c = cuenta.setdefault(rid, [0, 0]); c[0 if voto > 0 else 1] += 1
    return [(por_id[rid], a, b) for rid, (a, b) in cuenta.items()]

def main():
    if not os.path.exists(LOG):
        sys.exit("Todavía no hay preguntas guardadas (falta asistente_log.jsonl).")
    regs = []
    with open(LOG, encoding="utf-8") as f:
        for linea in f:
            try: regs.append(json.loads(linea))
            except Exception: pass
    if not regs:
        sys.exit("El registro está vacío.")

    grupos = []
    for r in regs:
        tk = toks(r["p"])
        g = max(grupos, key=lambda g: parecido(tk, g["tk"]), default=None)
        if g is None or parecido(tk, g["tk"]) < UMBRAL:
            g = {"tk": set(tk), "preg": Counter(), "users": set(), "sin_dato": 0, "ej": r["r"], "n": 0}
            grupos.append(g)
        g["preg"][r["p"].strip()] += 1
        g["users"].add(r.get("u"))
        g["n"] += 1
        if any(x in r["r"].lower() for x in NO_DATO):
            g["sin_dato"] += 1; g["ej_mala"] = r["r"]

    votadas = leer_votos(regs)
    malas = sorted([x for x in votadas if x[2] > x[1]], key=lambda x: (-x[2], x[0]["t"]))
    por_frec = sorted(grupos, key=lambda g: (-len(g["users"]), -g["n"]))
    sin_resp = sorted([g for g in grupos if g["sin_dato"]], key=lambda g: (-g["sin_dato"], -g["n"]))

    print(f"\n{len(regs)} preguntas | {len({r.get('u') for r in regs})} personas | {len(grupos)} temas distintos\n")
    print(f"=== LAS {min(TOP, len(por_frec))} MÁS REPETIDAS (personas distintas / veces) ===")
    for g in por_frec[:TOP]:
        print(f"  {len(g['users']):>3} / {g['n']:<3} {g['preg'].most_common(1)[0][0][:90]}")
    print("\n=== DONDE EL ASISTENTE DIJO QUE NO TENÍA EL DATO (conviene cargarlo) ===")
    for g in sin_resp[:TOP]:
        print(f"  {g['sin_dato']:>3} veces  {g['preg'].most_common(1)[0][0][:90]}")
    if not sin_resp:
        print("  (ninguna todavía)")
    if votadas:
        print(f"\n=== VOTOS: {sum(x[1] for x in votadas)} me sirvio / {sum(x[2] for x in votadas)} no me sirvio ===")
        print("Respuestas marcadas como malas (revisalas):")
        for r, a, b in malas[:TOP]:
            print(f"  {b} no / {a} si   {r['p'][:70]}  ->  {r['r'][:60]}")
        if not malas:
            print("  (ninguna)")

    with open(os.path.join(BASE, "preguntas_frecuentes.md"), "w", encoding="utf-8") as f:
        f.write("# Preguntas frecuentes detectadas\n\nCompletá la línea R: de las que quieras y pegalas en conocimiento/correcciones.md\n\n")
        if malas:
            f.write("## Respuestas marcadas con ↓ (prioridad)\n\n")
            for r, a, b in malas[:TOP]:
                f.write(f"P: {r['p'].strip()}\nR: ???   ({b} ↓ / {a} ↑ — el asistente dijo: {r['r'][:200].strip()})\n\n")
        f.write("## Sin respuesta (prioridad)\n\n")
        for g in sin_resp[:TOP]:
            vars_ = " ".join(p for p, _ in g["preg"].most_common(3))
            f.write(f"P: {vars_}\nR: ???   (el asistente dijo: {g.get('ej_mala','')[:120].strip()})\n\n")
        f.write("## Las más repetidas (revisá que estén bien respondidas)\n\n")
        for g in por_frec[:TOP]:
            vars_ = " ".join(p for p, _ in g["preg"].most_common(3))
            f.write(f"P: {vars_}\nR (hoy responde): {g['ej'][:300].strip()}\n\n")
    print("\nGuardé preguntas_frecuentes.md para completar y pasar a correcciones.md")

if __name__ == "__main__":
    main()
