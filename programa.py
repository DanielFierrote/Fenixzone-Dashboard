import ctypes, struct, subprocess, os, time, threading, json, math, argparse, hmac, socket, re
from http.server import HTTPServer, BaseHTTPRequestHandler

k32 = ctypes.windll.kernel32
psapi = ctypes.windll.psapi
psapi.EnumProcessModulesEx.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong,
                                       ctypes.POINTER(ctypes.c_ulong), ctypes.c_ulong]
psapi.GetModuleFileNameExW.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong]

PROCESS_ALL_ACCESS = 0x1F0FFF

SAMP_INFO_RVA, SAMP_POOLS_OFF, SAMP_PLAYERPOOL_OFF = 0x21A0F8, 0x3CD, 0x18
SAMP_REMOTE_OFF, SAMP_MAX_JUGADORES, SAMP_R1_ENTRY = 0x2E, 1004, 0x31DF13

SAMP_COLOR_OFFSET = 0x216378

OFF_NAME, OFF_NAME_SIZE, OFF_NAME_CAP = 0x0C, 0x1C, 0x20
OFF_SCORE, OFF_PING = 0x24, 0x28
OFF_INTERIOR = 0x3C
OFF_WEAPONS = 0x5C0


OFF_LOCAL_ID, OFF_LOCAL_NAME, OFF_LOCAL_NAME_SIZE, OFF_LOCAL_NAME_CAP = 0x04, 0x0A, 0x1A, 0x1E
OFF_LOCAL_PING, OFF_LOCAL_SCORE = 0x26, 0x2A

OFF_ENT_MATRIX, M_POS = 0x14, 0x30
OFF_HEALTH, OFF_ARMOR, OFF_WEAPON_SLOT = 0x540, 0x548 , 0x5BA
OFF_PED_VEHICLE = 0x58C
PED_PTR = 0xB6F5F0

PUERTO = 8000
LITE = False
TOKEN = os.environ.get("FZDB_TOKEN", "")

SERVIDORES_CONOCIDOS = {
    1: "s1.fenixzone.com",
    2: "s2.fenixzone.com",
}
FORZAR_SERVIDOR = None

def leer_mem(h, addr, n):
    buf = ctypes.create_string_buffer(n)
    leido = ctypes.c_size_t(0)
    ok = k32.ReadProcessMemory(h, addr, buf, n, ctypes.byref(leido))
    return buf.raw if ok and leido.value == n else None

def leer_u32(h, addr):
    d = leer_mem(h, addr, 4)
    return struct.unpack('<I', d)[0] if d else None

def leer_float(h, addr):
    d = leer_mem(h, addr, 4)
    return struct.unpack('<f', d)[0] if d else None

def leer_xyz(h, addr):
    d = leer_mem(h, addr, 12)
    return struct.unpack('<3f', d) if d else None
    
def arma_principal(h, ped):
    crudo = leer_mem(h, ped + OFF_WEAPONS, 13 * 16)
    if not crudo:
        return None
    mejor, mejor_ammo = 0, 0
    for i in range(13):
        tipo = crudo[i * 16]
        ammo = struct.unpack('<I', crudo[i * 16 + 4:i * 16 + 8])[0]
        if tipo != 0 and ammo > 0 and ammo > mejor_ammo:
            mejor_ammo = ammo
            mejor = tipo
    return mejor

def ptr_ok(p):
    return p is not None and 0x10000 < p < 0x7FFFFFFF

def obtener_pids(nombre):
    pids = []
    try:
        out = subprocess.check_output(
            ["tasklist", "/FI", f"IMAGENAME eq {nombre}", "/FO", "CSV", "/NH"],
            encoding="utf-8", errors="ignore")
        for l in out.strip().splitlines():
            p = [x.strip('"') for x in l.split('","')]
            if len(p) >= 2 and p[0].lower() == nombre.lower():
                pids.append(int(p[1]))
    except Exception:
        pass
    return pids

def base_modulo(h, nombre):
    buf = (ctypes.c_void_p * 1024)()
    needed = ctypes.c_ulong(0)
    if not psapi.EnumProcessModulesEx(h, ctypes.byref(buf), ctypes.sizeof(buf), ctypes.byref(needed), 0x03):
        return None
    ruta = ctypes.create_unicode_buffer(260)
    for i in range(min(1024, needed.value // ctypes.sizeof(ctypes.c_void_p))):
        mod = buf[i]
        if mod and psapi.GetModuleFileNameExW(h, mod, ruta, 260):
            if os.path.basename(ruta.value).lower() == nombre:
                return mod
    return None

class Panel:
    def __init__(self, h):
        self.h = h
        self.base = base_modulo(h, "samp.dll")
        self.con_nombres = False
        if self.base:
            pe = leer_u32(h, self.base + 0x3C)
            entrada = leer_u32(h, self.base + pe + 0x28) if pe is not None and 0 < pe < 0x1000 else None
            self.con_nombres = (entrada == SAMP_R1_ENTRY)

    def nombre(self, rp):
        return self.nombre_en(rp, OFF_NAME, OFF_NAME_SIZE, OFF_NAME_CAP)

    def nombre_en(self, base, off_nombre, off_tam, off_cap):
        tam, cap = leer_u32(self.h, base + off_tam), leer_u32(self.h, base + off_cap)
        if tam is None or cap is None or not (0 < tam <= 24):
            return None
        donde = base + off_nombre
        if cap >= 16:
            donde = leer_u32(self.h, base + off_nombre)
            if not ptr_ok(donde):
                return None
        dato = leer_mem(self.h, donde, tam)
        if not dato:
            return None
        try:
            txt = dato.decode("latin-1")
        except Exception:
            return None
        return txt if txt.isprintable() else None

    def color_de(self, jid):
        if not self.base:
            return None
        addr = self.base + SAMP_COLOR_OFFSET + jid * 4
        return leer_u32(self.h, addr)

    def jugadores(self):
        h = self.h
        info = leer_u32(h, self.base + SAMP_INFO_RVA)
        pools = leer_u32(h, info + SAMP_POOLS_OFF) if ptr_ok(info) else None
        pp = leer_u32(h, pools + SAMP_PLAYERPOOL_OFF) if ptr_ok(pools) else None
        if not ptr_ok(pp):
            return []
        crudo = leer_mem(h, pp + SAMP_REMOTE_OFF, SAMP_MAX_JUGADORES * 4)
        if not crudo:
            return []
        res = []
        for jid, rp in enumerate(struct.unpack('<%dI' % SAMP_MAX_JUGADORES, crudo)):
            if not ptr_ok(rp):
                continue
            nombre = self.nombre(rp) if self.con_nombres else None
            score = leer_u32(h, rp + OFF_SCORE)
            ping = leer_u32(h, rp + OFF_PING)
            if LITE:
                res.append({"id": jid, "nombre": nombre or f"Jugador {jid}", "vida": None, "chaleco": None,
                            "score": score, "ping": ping, "arma": None, "interior": None, "color": self.color_de(jid),
                            "en_auto": False, "pos": None})
                continue
            interior = leer_u32(h, rp + OFF_INTERIOR)
            color = self.color_de(jid)
            datos = leer_u32(h, rp)
            actor = leer_u32(h, datos) if ptr_ok(datos) else None
            ped = leer_u32(h, actor + 0x40) if ptr_ok(actor) else None
            if not ptr_ok(ped):
                res.append({"id": jid, "nombre": nombre or f"Jugador {jid}",
                            "vida": None, "chaleco": None, "score": score, "ping": ping,
                            "arma": None, "interior": interior, "color": color,
                            "en_auto": False, "pos": None})
                continue
            vida = leer_float(h, ped + OFF_HEALTH)
            chaleco = leer_float(h, ped + OFF_ARMOR)
            arma = arma_principal(h, ped)
            veh = leer_u32(h, ped + OFF_PED_VEHICLE)
            mat = leer_u32(h, ped + OFF_ENT_MATRIX)
            pos = leer_xyz(h, mat + M_POS) if ptr_ok(mat) else None
            res.append({"id": jid, "nombre": nombre or f"Jugador {jid}",
                        "vida": vida, "chaleco": chaleco, "score": score, "ping": ping,
                        "arma": arma, "interior": interior, "color": color,
                        "en_auto": ptr_ok(veh), "pos": pos})
        try:
            lid = leer_mem(h, pp + OFF_LOCAL_ID, 2)
            lid = struct.unpack('<H', lid)[0] if lid else None
            lnombre = self.nombre_en(pp, OFF_LOCAL_NAME, OFF_LOCAL_NAME_SIZE, OFF_LOCAL_NAME_CAP) if self.con_nombres else None
            if lnombre and lid is not None and lid < SAMP_MAX_JUGADORES and all(x["id"] != lid for x in res):
                lping = leer_u32(h, pp + OFF_LOCAL_PING)
                res.append({"id": lid, "nombre": lnombre, "vida": None, "chaleco": None,
                            "score": leer_u32(h, pp + OFF_LOCAL_SCORE),
                            "ping": lping if lping is not None and lping < 10000 else None,
                            "arma": None, "interior": None, "color": self.color_de(lid),
                            "en_auto": False, "pos": None, "yo": True})
        except Exception:
            pass
        return res
    

def mi_posicion(h):
    ped = leer_u32(h, PED_PTR)
    mat = leer_u32(h, ped + OFF_ENT_MATRIX) if ptr_ok(ped) else None
    p = leer_xyz(h, mat + M_POS) if ptr_ok(mat) else None
    return p

estado = {"jugadores": [], "mi_pos": None, "error": "", "ts": 0,
          "servidor": None, "servidor_dir": ""}

def leer_en_bucle(h, panel):
    while True:
        try:
            if not panel.base:
                estado["error"] = "No encontre samp.dll o no estas conectado a un servidor."
            else:
                estado["jugadores"] = panel.jugadores()
                estado["mi_pos"] = mi_posicion(h)
                estado["error"] = ""
                estado["ts"] = time.time()
        except Exception as e:
            estado["error"] = str(e)
        time.sleep(1.0)

_RE_IP = re.compile(r"\d{1,3}(\.\d{1,3}){3}")
_RE_HOST = re.compile(r"[A-Za-z0-9][A-Za-z0-9.-]*[A-Za-z0-9]")
_dns = {}

def _resolver(nombre):
    try:
        return socket.gethostbyname_ex(nombre)[2]
    except Exception:
        return []

def ips_de(texto):
    if _RE_IP.fullmatch(texto):
        return [texto]
    ahora = time.time()
    c = _dns.get(texto)
    if c and ahora - c[0] < 600:
        return c[1]
    ips = _resolver(texto)
    _dns[texto] = (ahora if ips else ahora - 540, ips)
    return ips

def _parece_direccion(t):
    if _RE_IP.fullmatch(t):
        return all(int(x) <= 255 for x in t.split("."))
    return "." in t and bool(_RE_HOST.fullmatch(t)) and not re.fullmatch(r"[\d.]+", t)

def leer_direcciones(h, base):
    info = leer_u32(h, base + SAMP_INFO_RVA)
    if not ptr_ok(info):
        return []
    blob = b""
    for off in range(0, 0x400, 0x100):
        parte = leer_mem(h, info + off, 0x100)
        blob += parte if parte else b"\0" * 0x100
    res = []
    for m in re.finditer(rb"[\x20-\x7e]{4,}", blob):
        t = re.sub(r":\d+$", "", m.group().decode("ascii").strip())
        if _parece_direccion(t) and t not in res:
            res.append(t)
    return res

def detectar_servidor(candidatas):
    for t in candidatas:
        for sid, host in SERVIDORES_CONOCIDOS.items():
            if t.lower() == host.lower():
                return sid
    ips_srv = {sid: set(ips_de(host)) for sid, host in SERVIDORES_CONOCIDOS.items()}
    for t in candidatas:
        ips = set(ips_de(t))
        if not ips:
            continue
        hits = [sid for sid, s in ips_srv.items() if ips & s]
        if len(hits) == 1:
            return hits[0]
    return None

def vigilar_servidor(h, panel):
    ultimo = None
    while True:
        try:
            cand = leer_direcciones(h, panel.base) if panel.base else []
            sid = detectar_servidor(cand)
            dir_ = cand[0] if cand else ""
            estado["servidor"], estado["servidor_dir"] = sid, dir_
            if (sid, dir_) != ultimo:
                ultimo = (sid, dir_)
                if sid:
                    print(f"  [servidor] Detectado: SERVIDOR {sid} ({dir_})", flush=True)
                elif dir_:
                    print(f"  [servidor] Conectado a {dir_}: no es ninguno de los servidores configurados "
                          f"({', '.join(map(str, SERVIDORES_CONOCIDOS))}).", flush=True)
                else:
                    print("  [servidor] No pude leer la direccion del servidor. "
                          "Si hace falta, usa --servidor 1 o --servidor 2.", flush=True)
        except Exception:
            pass
        time.sleep(2.0)

PAGE = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SAMP Panel de Jugadores</title>
<style>
  :root{
    --bg:#0f1118; --panel:#171a24; --panel2:#1e2230; --borde:#262b3a;
    --fg:#e8eaf0; --gris:#8f95ad; --azul:#6ea8ff; --verde:#3ddc84;
    --amarillo:#ffd166; --rojo:#ff6b6b; --violeta:#b48cff;
  }
  *{box-sizing:border-box}
  body{background:var(--bg);color:var(--fg);font-family:'Segoe UI',Arial,sans-serif;margin:0;padding:24px}
  .wrap{max-width:1300px;margin:0 auto}
  header{display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:12px;margin-bottom:6px}
  h1{font-size:22px;margin:0}
  h1 span{color:var(--azul)}
  .sub{color:var(--gris);font-size:13px;margin-bottom:18px}
  .stats{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:18px}
  .stat{background:var(--panel);border:1px solid var(--borde);border-radius:10px;padding:10px 16px;min-width:120px}
  .stat b{display:block;font-size:20px}
  .stat span{color:var(--gris);font-size:12px;text-transform:uppercase;letter-spacing:.5px}
  .stat.s1 b{color:var(--azul)} .stat.s2 b{color:var(--amarillo)} .stat.s3 b{color:var(--verde)}
  .controles{display:flex;gap:10px;align-items:center;margin-bottom:14px;flex-wrap:wrap}
  .buscar{flex:1;min-width:220px;background:var(--panel);border:1px solid var(--borde);border-radius:8px;
          display:flex;align-items:center;padding:0 12px;gap:8px}
  .buscar input{background:none;border:none;outline:none;color:var(--fg);font-size:14px;width:100%;padding:11px 0}
  .buscar input::placeholder{color:var(--gris)}
  .buscar .ico{color:var(--gris)}
  .filtro{background:var(--panel);border:1px solid var(--borde);border-radius:8px;padding:11px 12px;
          color:var(--fg);font-size:14px;outline:none;cursor:pointer}
  .filtro option{background:var(--panel)}
  table{width:100%;border-collapse:collapse;background:var(--panel);border-radius:10px;overflow:hidden}
  th{text-align:left;padding:11px 14px;color:var(--gris);font-size:12px;text-transform:uppercase;
     letter-spacing:.5px;cursor:pointer;user-select:none;white-space:nowrap;border-bottom:1px solid var(--borde)}
  th:hover{color:var(--fg);background:var(--panel2)}
  th .arr{display:inline-block;width:14px;color:var(--azul);font-size:11px}
  td{padding:10px 14px;border-top:1px solid var(--borde);font-size:14px}
  tr:hover td{background:var(--panel2)}
  .id{color:var(--azul);font-weight:bold;width:50px}
  .score{color:var(--amarillo);font-weight:bold}
  .nombre{font-weight:500}
  .nombre.poli{color:var(--azul);font-weight:700}
  .ping{font-family:Consolas,monospace}
  .ping.bueno{color:var(--verde)} .ping.medio{color:var(--amarillo)} .ping.malo{color:var(--rojo)}
  .arma{color:var(--violeta)}
  .colorchips{display:flex;gap:5px;align-items:center}
  .chip{width:16px;height:16px;border-radius:4px;border:1px solid #00000055;display:inline-block}
  .colorhex{color:var(--gris);font-size:11px;font-family:Consolas,monospace}
  .barra{background:#262b3a;border-radius:6px;height:9px;width:110px;overflow:hidden}
  .fill{height:100%;border-radius:6px;transition:width .3s}
  .vida{display:flex;align-items:center;gap:8px;color:var(--gris);font-size:13px}
  .enauto{color:var(--amarillo);font-size:12px}
  .apie{color:var(--gris);font-size:12px}
  .lejos{color:var(--gris)}
  .interior{font-family:Consolas,monospace}
  .interior.fuera{color:var(--gris)} .interior.dentro{color:var(--violeta)}
  .err{color:var(--rojo);margin-top:14px}
  .vacio{color:var(--gris);text-align:center;padding:30px}
  .pie{color:var(--gris);font-size:12px;margin-top:14px}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>🎮 <span>SAMP</span> Panel de Jugadores</h1>
    <div id="estado" class="sub" style="margin:0"></div>
  </header>

  <div class="stats">
    <div class="stat s1"><b id="st_total">0</b><span>Jugadores</span></div>
    <div class="stat s2"><b id="st_auto">0</b><span>En auto</span></div>
    <div class="stat s3"><b id="st_score">0</b><span>Score prom.</span></div>
  </div>

  <div class="controles">
    <div class="buscar"><span class="ico">🔍</span>
      <input id="buscar" type="text" placeholder="Buscar por nombre o ID...">
    </div>
    <select id="filtro" class="filtro">
      <option value="todos">Todos</option>
      <option value="policia">👮 Policías</option>
      <option value="auto">Solo en auto</option>
      <option value="pie">Solo a pie</option>
      <option value="cerca">Solo cerca</option>
      <option value="interior">Solo en interior</option>
    </select>
  </div>

  <table>
    <thead><tr>
      <th data-k="id">ID<span class="arr"></span></th>
      <th data-k="nombre">Jugador<span class="arr"></span></th>
      <th data-k="score">Score<span class="arr"></span></th>
      <th>Color</th>
      <th data-k="vida">Vida<span class="arr"></span></th>
      <th data-k="chaleco">Chaleco<span class="arr"></span></th>
      <th data-k="ping">Ping<span class="arr"></span></th>
      <th data-k="arma">Arma<span class="arr"></span></th>
      <th data-k="interior">Int.<span class="arr"></span></th>
      <th>Estado</th>
      <th data-k="dist">Distancia<span class="arr"></span></th>
    </tr></thead>
    <tbody id="filas"></tbody>
  </table>
  <div class="err" id="err"></div>
  <div class="pie" id="pie"></div>
</div>

<script>
const datos = {jugadores:[], mi_pos:null};
let sortKey = 'score', sortDir = -1;   // por defecto: score de mayor a menor

// ── COLORES DE LOS POLICIAS (lista: agregá o sacá los que uses) ──
const COLORES_POLICIA = [0x5AC8FA, 0x99FF00];   // azul + el verde de Sophie

// ── NOMBRES DE ARMAS (ID -> nombre) ──
const ARMAS = {
  0:'Puños',1:'Manopla',2:'Palo de golf',3:'Porra',4:'Cuchillo',5:'Bate',
  6:'Pala',7:'Taco de billar',8:'Katana',9:'Motosierra',
  10:'Consolador',11:'Consolador',12:'Consolador',13:'Consolador',
  14:'Flores',15:'Bastón',16:'Granada',17:'Gas lacrimógeno',18:'Cóctel molotov',
  19:'Rocket',20:'Rocket',21:'Bomba',22:'Colt 45',23:'9mm silenciada',
  24:'Desert Eagle',25:'Escopeta',26:'Escopeta recortada',27:'Escopeta de combate',
  28:'Uzi',29:'MP5',30:'AK-47',31:'M4',32:'Tec-9',33:'Rifle',34:'Francotirador',
  35:'Lanzacohetes',36:'Lanzacohetes',37:'Lanzallamas',38:'Minigun',
  39:'Carga explosiva',40:'Detonador',41:'Pintura',42:'Extintor',43:'Cámara',
  44:'Visión nocturna',45:'Visión infrarroja',46:'Paracaídas',47:'Pistola falsa'
};
function armaNombre(id){
  if(id==null) return '?';
  return ARMAS[id] || ('Arma '+id);
}

function esc(t){return String(t).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function color(p){ return p>50 ? '#3ddc84' : (p>25 ? '#ffd166' : '#ff6b6b'); }
function barra(p){
  if(p==null) return '<span style="color:#8f95ad">?</span>';
  p = Math.max(0, Math.min(p, 100));
  return '<div class="vida"><span>'+p.toFixed(1)+'</span><div class="barra"><div class="fill" style="width:'+p+'%;background:'+color(p)+'"></div></div></div>';
}
function dist(j){
  if(!j.pos || !datos.mi_pos) return null;
  const dx=j.pos[0]-datos.mi_pos[0], dy=j.pos[1]-datos.mi_pos[1];
  return Math.sqrt(dx*dx+dy*dy);
}
function ahex(c){
  if(c==null) return null;
  c = c>>>0;
  const r=(c>>16)&255, g=(c>>8)&255, b=c&255;
  return '#'+[r,g,b].map(x=>x.toString(16).padStart(2,'0')).join('').toUpperCase();
}
function esPolicia(j){
  if(j.color==null) return false;
  const rgb = (j.color>>>0)&0xFFFFFF;
  return COLORES_POLICIA.some(c => (c&0xFFFFFF) === rgb);
}
function pingCls(p){
  if(p==null) return '';
  return p<100 ? 'bueno' : (p<250 ? 'medio' : 'malo');
}

document.querySelectorAll('th[data-k]').forEach(th=>{
  th.addEventListener('click', ()=>{
    const k = th.dataset.k;
    if(sortKey===k) sortDir = -sortDir;
    else{ sortKey=k; sortDir = (k==='nombre') ? 1 : -1; }
    render();
  });
});

function render(){
  const q = document.getElementById('buscar').value.trim().toLowerCase();
  const filtro = document.getElementById('filtro').value;

  let lista = datos.jugadores.filter(j=>{
    if(q && !(j.nombre.toLowerCase().includes(q) || String(j.id).includes(q))) return false;
    if(filtro==='policia' && !esPolicia(j)) return false;
    if(filtro==='auto' && !j.en_auto) return false;
    if(filtro==='pie' && j.en_auto) return false;
    if(filtro==='cerca' && (j.pos==null || dist(j)==null)) return false;
    if(filtro==='interior' && !(j.interior>0)) return false;
    return true;
  });

  const val = j => {
    if(sortKey==='dist') return dist(j)==null ? Infinity : dist(j);
    if(sortKey==='vida'||sortKey==='chaleco') return j[sortKey]==null ? -1 : j[sortKey];
    if(sortKey==='ping'||sortKey==='interior') return j[sortKey]==null ? -1 : j[sortKey];
    if(sortKey==='arma') return armaNombre(j.arma);
    return j[sortKey];
  };
  lista.sort((a,b)=>{
    const va=val(a), vb=val(b);
    if(va==vb) return a.id-b.id;
    if(typeof va==='string') return va.localeCompare(vb)*sortDir;
    return (va-vb)*sortDir;
  });

  document.querySelectorAll('th[data-k]').forEach(th=>{
    th.querySelector('.arr').textContent = (th.dataset.k===sortKey) ? (sortDir>0?' ▲':' ▼') : '';
  });

  const tb = document.getElementById('filas');
  tb.innerHTML = '';
  if(!lista.length){
    tb.innerHTML = '<tr><td colspan="11" class="vacio">Sin resultados</td></tr>';
  }
  for(const j of lista){
    const d = dist(j);
    const distTxt = d!=null ? Math.round(d)+' m' : (j.pos ? '?' : 'lejos');
    const hex = ahex(j.color);
    const colorTd = hex
      ? '<div class="colorchips"><span class="chip" style="background:'+hex+'"></span><span class="colorhex">'+hex+'</span></div>'
      : '<span class="lejos">?</span>';
    const nombreCls = 'nombre' + (esPolicia(j) ? ' poli' : '');
    const pingTd = j.ping!=null
      ? '<span class="ping '+pingCls(j.ping)+'">'+j.ping+' ms</span>'
      : '<span class="lejos">?</span>';
    const armaTd = '<span class="arma">'+armaNombre(j.arma)+'</span>';
    const intTd = (j.interior!=null && j.interior>0)
      ? '<span class="interior dentro">'+j.interior+'</span>'
      : '<span class="interior fuera">0</span>';
    const tr = document.createElement('tr');
        tr.innerHTML = '<td class="id">'+j.id+'</td>'+
      '<td class="'+nombreCls+'">'+esc(j.nombre)+'</td>'+
      '<td class="score">'+(j.score==null?'?':j.score)+'</td>'+
      '<td>'+colorTd+'</td>'+
      '<td>'+barra(j.vida)+'</td>'+
      '<td>'+barra(j.chaleco)+'</td>'+
      '<td>'+pingTd+'</td>'+
      '<td>'+armaTd+'</td>'+
      '<td>'+intTd+'</td>'+
      '<td>'+(j.en_auto ? '<span class="enauto">🚗 en auto</span>' : '<span class="apie">a pie</span>')+'</td>'+
      '<td class="lejos">'+distTxt+'</td>';

    tb.appendChild(tr);
  }
  document.getElementById('pie').textContent = 'Mostrando '+lista.length+' de '+datos.jugadores.length+' jugadores';
}

async function actualizar(){
  try{
    const r = await fetch('/api');
    const d = await r.json();
    datos.jugadores = d.jugadores;
    datos.mi_pos = d.mi_pos;
    document.getElementById('estado').textContent = d.error ||
      (d.servidor ? '● Servidor ' + d.servidor : (d.servidor_dir ? 'Servidor no reconocido: ' + d.servidor_dir : ''));
    document.getElementById('err').textContent = '';
    const n = d.jugadores.length;
    document.getElementById('st_total').textContent = n;
    document.getElementById('st_auto').textContent = d.jugadores.filter(j=>j.en_auto).length;
    const scores = d.jugadores.map(j=>j.score).filter(s=>s!=null);
    document.getElementById('st_score').textContent = scores.length ? Math.round(scores.reduce((a,b)=>a+b,0)/scores.length) : 0;
    render();
  }catch(e){
    document.getElementById('err').textContent = 'No se pudo conectar al servidor local.';
  }
}
document.getElementById('buscar').addEventListener('input', render);
document.getElementById('filtro').addEventListener('change', render);
actualizar();
setInterval(actualizar, 1000);
</script>
</body>
</html>"""

class Handler(BaseHTTPRequestHandler):
    def autorizado(self):
        if not TOKEN or self.client_address[0] in ("127.0.0.1", "::1"):
            return True
        return hmac.compare_digest(self.headers.get("X-Token", "").encode(), TOKEN.encode())
    def do_GET(self):
        if not self.autorizado():
            self.send_response(403); self.end_headers(); return
        if self.path.startswith("/api"):
            cuerpo = json.dumps(estado).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.end_headers()
            self.wfile.write(cuerpo)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(PAGE.encode())
    def log_message(self, *a):
        pass

def main():
    global PUERTO, LITE, TOKEN, FORZAR_SERVIDOR
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", type=int, help="PID de gta_sa.exe (si hay varios clientes abiertos)")
    ap.add_argument("--puerto", type=int, default=PUERTO, help="puerto HTTP (8000, 8001...)")
    ap.add_argument("--lite", action="store_true", help="solo id, nombre, score y ping")
    ap.add_argument("--host", default="127.0.0.1", help="0.0.0.0 para que otra PC de tu red lo lea (usar con --token)")
    ap.add_argument("--token", default=TOKEN, help="clave compartida con fzdb_server.py")
    ap.add_argument("--servidor", type=int, choices=sorted(SERVIDORES_CONOCIDOS),
                    help="fija el servidor a mano (solo si la deteccion automatica no funciona)")
    a = ap.parse_args()
    PUERTO, LITE, TOKEN, FORZAR_SERVIDOR = a.puerto, a.lite, a.token, a.servidor

    print("=" * 50)
    print("  SAMP Panel Web de Jugadores v5")
    print("=" * 50)

    pids = obtener_pids("gta_sa.exe")
    if not pids:
        print("  ❌ gta_sa.exe no encontrado"); input(); return
    pid = a.pid
    if pid is None:
        if len(pids) == 1:
            pid = pids[0]
        else:
            print("  Hay varios gta_sa.exe abiertos: " + ", ".join(map(str, pids)))
            print("  Volvé a ejecutar con --pid <numero> --puerto <8000|8001>")
            input(); return
    elif pid not in pids:
        print(f"  ❌ El PID {pid} no es un gta_sa.exe (abiertos: {pids})"); input(); return
    if a.host != "127.0.0.1" and not TOKEN:
        print("  ⚠️  Abierto a la red SIN --token: cualquiera en tu red puede leer la lista.")
    h = k32.OpenProcess(0x0410, False, pid)
    if not h:
        print("  ❌ No se pudo abrir el proceso. ¿Lo corriste como Admin?"); input(); return
    print(f"\n  PID: {pid}")

    panel = Panel(h)
    if not panel.base:
        print("  ⚠️  No encontre samp.dll (¿ya estas dentro del servidor?).")
    elif not panel.con_nombres:
        print("  ⚠️  Tu samp.dll no es 0.3.7-R1: los nombres salen como 'Jugador N'.")

    threading.Thread(target=leer_en_bucle, args=(h, panel), daemon=True).start()
    if FORZAR_SERVIDOR:
        estado["servidor"], estado["servidor_dir"] = FORZAR_SERVIDOR, "manual"
        print(f"  [servidor] Fijado a mano: SERVIDOR {FORZAR_SERVIDOR}")
    else:
        threading.Thread(target=vigilar_servidor, args=(h, panel), daemon=True).start()

    try:
        server = HTTPServer((a.host, PUERTO), Handler)
    except OSError:
        print(f"  ❌ El puerto {PUERTO} ya esta en uso. Cerrá el otro programa o cambia PUERTO.")
        k32.CloseHandle(h); input(); return

    print(f"  ✅ Abri en el navegador:  http://localhost:{PUERTO}")
    print(f"     (Se actualiza sola. Ctrl+C en la consola para salir)\n")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        k32.CloseHandle(h)
        print("\n  Bye!")

if __name__ == "__main__":
    main()

