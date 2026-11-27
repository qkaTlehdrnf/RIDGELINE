"""Turn a recorded war (tools/record_war.py: <name>.rlr + <name>.json) into ONE small self-contained page that plays on a phone:
plain 2D canvas, half-day steps, territory colours, unit dots per province, battles, depots, tap for details.

  python tools/make_mobile.py runs/replays/war out.html [--title "..."] [--step 12]
"""
import base64, json, os, sys, zlib
import numpy as np
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rlr_tools as R

PAGE = r"""<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1,user-scalable=no">
<title>__TITLE__</title><style>
html,body{margin:0;height:100%;background:#0d1117;color:#e6edf3;font:14px/1.35 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Noto Sans KR",sans-serif;overflow:hidden;overscroll-behavior:none}
#wrap{display:flex;flex-direction:column;height:100%}
#top{padding:8px 12px 4px;display:flex;justify-content:space-between;align-items:baseline;gap:8px}
#top b{font-size:15px}#day{font-variant-numeric:tabular-nums;color:#9da7b3;white-space:nowrap}
#mapbox{position:relative;flex:0 0 46%;min-height:150px;touch-action:none;background:#0a1622}
canvas{position:absolute;left:0;top:0;width:100%;height:100%}
#tip{position:absolute;left:8px;top:8px;max-width:75%;background:rgba(13,17,23,.88);border:1px solid #30363d;border-radius:8px;padding:6px 9px;font-size:13px;display:none}
#ev{position:absolute;left:8px;bottom:6px;right:8px;font-size:12px;color:#fff;text-shadow:0 1px 2px #000;pointer-events:none}
#ctl{padding:6px 12px;display:flex;align-items:center;gap:10px}
button{background:#21262d;color:#e6edf3;border:1px solid #30363d;border-radius:8px;font-size:15px;padding:8px 12px;min-width:44px}
button.on{background:#1f6feb;border-color:#1f6feb}
input[type=range]{flex:1;height:32px;accent-color:#58a6ff}
#stats{padding:0 12px 4px;color:#9da7b3;font-size:12.5px;font-variant-numeric:tabular-nums}
#list{flex:1 1 0;overflow-y:auto;padding:2px 12px 10px;font-size:13px;border-top:1px solid #21262d;-webkit-overflow-scrolling:touch}
.row{display:flex;align-items:center;gap:8px;padding:3px 0}.sw{width:12px;height:12px;border-radius:3px;flex:none}
.row span.n{flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.row span.v{color:#9da7b3;font-variant-numeric:tabular-nums;white-space:nowrap}
.dead{opacity:.45;text-decoration:line-through}.sel{background:#161b22;border-radius:6px}
#legend{font-size:11.5px;color:#9da7b3;padding:0 12px 4px}
</style></head><body><div id="wrap">
<div id="top"><b>__TITLE__</b><span id="day"></span></div>
<div id="mapbox"><canvas id="c"></canvas><div id="tip"></div><div id="ev"></div></div>
<div id="ctl"><button id="play">▶</button><input id="sl" type="range" min="0" value="0"><button id="spd">1x</button><button id="fit">⤢</button></div>
<div id="stats"></div>
<div id="legend">점 = 그 지역의 유닛 수, 빨간 고리 = 돌격 중, 흰 네모 = 보급 거점, 주황 마름모 = 도시(확대하면 이름), ★ = 수도. 지도는 끌고 두 손가락으로 확대, 지역이나 진영을 누르면 자세히.</div>
<div id="list"></div></div>
<script>
const DATA=__DATA__;
const b64=s=>{const b=atob(s),a=new Uint8Array(b.length);for(let i=0;i<b.length;i++)a[i]=b.charCodeAt(i);return a};
const GW=DATA.gw,GH=DATA.gh,P=DATA.px.length,NF=DATA.factions.length,F=DATA.t.length;
const cellsB=b64(DATA.cells),cells=new Int16Array(cellsB.buffer);
const cnt=b64(DATA.counts);                       // F x P unit counts (0-255, x COUNT_DIV)
const COL=DATA.colors;const land=DATA.land;
// ownership per frame, rebuilt from changes
const own=[];{let cur=Int8Array.from(DATA.owner0);own.push(cur);for(let f=1;f<F;f++){cur=cur.slice();const ch=DATA.changes[f]||[];for(let i=0;i<ch.length;i+=2)cur[ch[i]]=ch[i+1];own.push(cur)}}
const off=document.createElement('canvas');off.width=GW;off.height=GH;const octx=off.getContext('2d');const img=octx.createImageData(GW,GH);
const c=document.getElementById('c'),ctx=c.getContext('2d'),box=document.getElementById('mapbox');
let fr=0,playing=false,speed=1,sel=-1,selP=-1,cam={x:GW/2,y:GH/2,s:1},lastPaint=-1,lastSel=-2;
function paintMap(){const o=own[fr],d=img.data;for(let i=0;i<GW*GH;i++){const p=cells[i];let r=10,g=22,b=34;if(p>=0&&land[p]){const w=o[p];if(w<0){r=58;g=62;b=66}else{const k=COL[w];r=k[0];g=k[1];b=k[2];if(sel>=0&&w!==sel){r=r*.3+30;g=g*.3+32;b=b*.3+34}}
 const x=i%GW;if((x+1<GW&&cells[i+1]!==p&&cells[i+1]>=0&&o[cells[i+1]]!==w)||(i+GW<GW*GH&&cells[i+GW]!==p&&cells[i+GW]>=0&&o[cells[i+GW]]!==w)){r*=.45;g*=.45;b*=.45}}
 d[i*4]=r;d[i*4+1]=g;d[i*4+2]=b;d[i*4+3]=255}octx.putImageData(img,0,0);lastPaint=fr;lastSel=sel}
function fit(){const w=box.clientWidth,h=box.clientHeight;cam.s=Math.min(w/GW,h/GH);cam.x=GW/2;cam.y=GH/2}
function resize(){const r=devicePixelRatio||1;c.width=box.clientWidth*r;c.height=box.clientHeight*r;draw()}
function sx(x){return (x-cam.x)*cam.s+box.clientWidth/2}function sy(y){return (y-cam.y)*cam.s+box.clientHeight/2}
function draw(){if(lastPaint!==fr||lastSel!==sel)paintMap();const r=devicePixelRatio||1,w=box.clientWidth,h=box.clientHeight;ctx.setTransform(r,0,0,r,0,0);ctx.fillStyle='#0a1622';ctx.fillRect(0,0,w,h);
 ctx.imageSmoothingEnabled=cam.s<3;ctx.drawImage(off,sx(0),sy(0),GW*cam.s,GH*cam.s);
 ctx.strokeStyle='rgba(70,150,235,.9)';ctx.lineWidth=Math.max(1,cam.s*.35);ctx.lineJoin='round';for(const rv of DATA.rivers||[]){ctx.beginPath();for(let i=0;i<rv.length;i+=2){const x=sx(rv[i]),y=sy(rv[i+1]);i?ctx.lineTo(x,y):ctx.moveTo(x,y)}ctx.stroke()}
 const base=fr*P,o=own[fr],k=Math.max(.6,Math.min(3,cam.s*.9));
 for(let p=0;p<P;p++){const n=cnt[base+p];if(!n||!land[p])continue;const x=sx(DATA.px[p]),y=sy(DATA.py[p]);if(x<-9||y<-9||x>w+9||y>h+9)continue;const rad=k*(0.35+Math.sqrt(n*DATA.div)*.2);
  ctx.beginPath();ctx.arc(x,y,rad,0,7);ctx.fillStyle=(sel>=0&&o[p]!==sel)?'rgba(255,255,255,.2)':'rgba(255,255,255,.75)';ctx.fill();ctx.lineWidth=.5;ctx.strokeStyle='rgba(0,0,0,.5)';ctx.stroke()}
 const bt=DATA.battles[fr]||[];ctx.strokeStyle='#ff3b30';ctx.lineWidth=Math.max(1.5,k);for(const p of bt){ctx.beginPath();ctx.arc(sx(DATA.px[p]),sy(DATA.py[p]),4+3*k,0,7);ctx.stroke()}
 const dp=DATA.depots[Math.min(DATA.depots.length-1,fr)]||[];for(let f=0;f<NF;f++){const m=dp[f]||{};for(const d in m){const x=sx(DATA.px[d]),y=sy(DATA.py[d]),q=5+2.5*k;ctx.fillStyle='#fff';ctx.strokeStyle='#000';ctx.lineWidth=1;ctx.fillRect(x-q/2,y-q/2,q,q);ctx.strokeRect(x-q/2,y-q/2,q,q)}}
 {const q=2.2+1.6*k;ctx.lineWidth=1;ctx.strokeStyle='#1a1205';ctx.fillStyle='#ff9f0a';for(const c of DATA.cities||[]){const x=sx(DATA.px[c]),y=sy(DATA.py[c]);if(x<-9||y<-9||x>w+9||y>h+9)continue;ctx.beginPath();ctx.moveTo(x,y-q);ctx.lineTo(x+q,y);ctx.lineTo(x,y+q);ctx.lineTo(x-q,y);ctx.closePath();ctx.fill();ctx.stroke()}
  if(cam.s>=5){ctx.font='10px sans-serif';ctx.textAlign='center';ctx.textBaseline='top';ctx.lineWidth=3;ctx.strokeStyle='rgba(0,0,0,.75)';ctx.fillStyle='#ffd9a0';for(const c of DATA.cities||[]){const nm=DATA.names[c];if(!nm)continue;const x=sx(DATA.px[c]),y=sy(DATA.py[c]);if(x<-40||y<-9||x>w+40||y>h+9)continue;ctx.strokeText(nm,x,y+q+1);ctx.fillText(nm,x,y+q+1)}}}
 ctx.fillStyle='#ffd60a';ctx.fillStyle='#b8860b';ctx.font=(5+2.5*k)+'px sans-serif';ctx.textAlign='center';ctx.textBaseline='middle';for(let f=0;f<NF;f++){const cp=DATA.capitals[f];if(o[cp]===f)ctx.fillText('★',sx(DATA.px[cp]),sy(DATA.py[cp]))}
 {const st=DATA.side[Math.min(DATA.side.length-1,fr)]||{};for(const z of st.sea||[]){const x=sx(DATA.px[z[0]]),y=sy(DATA.py[z[0]]),q=(z[2]===1?3:2)+1.2*k+Math.sqrt(z[3])*.5,cl=COL[z[1]];ctx.fillStyle='rgb('+cl.join(',')+')';ctx.strokeStyle=z[2]===1?'#fff':'#000';ctx.lineWidth=1;ctx.beginPath();if(z[2]===1){ctx.moveTo(x,y-q);ctx.lineTo(x+q,y);ctx.lineTo(x,y+q);ctx.lineTo(x-q,y)}else if(z[2]===2){ctx.moveTo(x,y-q);ctx.lineTo(x+q,y+q);ctx.lineTo(x-q,y+q)}else ctx.rect(x-q*.7,y-q*.7,q*1.4,q*1.4);ctx.closePath();ctx.fill();ctx.stroke()}}
 if(selP>=0){ctx.strokeStyle='#fff';ctx.lineWidth=2;ctx.beginPath();ctx.arc(sx(DATA.px[selP]),sy(DATA.py[selP]),9,0,7);ctx.stroke()}
 ui()}
const ERA=['고대','중세','화약','산업','세계대전','현대','우주'];
function ui(){const t=DATA.t[fr];document.getElementById('day').textContent=Math.min(Math.floor(t/24)+1,Math.ceil(DATA.t[F-1]/24))+'일차 / '+Math.ceil(DATA.t[F-1]/24)+'일'+(DATA.years?' · 서기 '+Math.round(t*DATA.years/DATA.t[F-1])+'년':'');
 const o=own[fr],pc=new Array(NF).fill(0),uc=new Array(NF).fill(0);for(let p=0;p<P;p++){const w=o[p];if(w>=0){pc[w]++;uc[w]+=cnt[fr*P+p]*DATA.div}}
 const alive=pc.filter(v=>v>0).length,dp=DATA.depots[Math.min(DATA.depots.length-1,fr)]||[];const st=DATA.side[Math.min(DATA.side.length-1,fr)]||{};
 document.getElementById('stats').textContent='남은 진영 '+alive+' · 불가침 협정 '+(st.pacts||0)+(DATA.years?' · 전쟁 중인 관계 '+(st.wars||0):'')+' · 지금까지 실제 공격 '+(st.att||0)+'회 (성공 '+(st.won||0)+')';
 const ord=[...Array(NF).keys()].sort((a,b)=>pc[b]-pc[a]);let h='';for(const f of ord){const nd=Object.keys(dp[f]||{}).length;h+='<div class="row'+(pc[f]?'':' dead')+(sel===f?' sel':'')+'" data-f="'+f+'"><span class="sw" style="background:rgb('+COL[f].join(',')+')"></span><span class="n">'+DATA.factions[f]+' <small style="color:#6e7681">'+DATA.models[f]+'</small></span><span class="v">'+(st.era?ERA[st.era[f]]+' · ':'')+'땅 '+pc[f]+' · 유닛 '+uc[f]+(st.ships&&st.ships[f]?' · 함선 '+st.ships[f]:'')+(st.air&&st.air[f]?' · 항공기 '+st.air[f]:'')+'</span></div>'}
 document.getElementById('list').innerHTML=h;
 let e='';for(let i=Math.max(0,fr-5);i<=fr;i++)for(const x of (DATA.events[i]||[]))e=x;document.getElementById('ev').textContent=e;
 if(selP>=0){const w=o[selP],tip=document.getElementById('tip');let d='';if(w>=0&&dp[w]&&dp[w][selP]!==undefined)d='<br>보급 거점 (재산의 '+Math.round(dp[w][selP]*100)+'% 보관)';tip.style.display='block';tip.innerHTML='<b>P'+selP+'</b> '+(DATA.names[selP]||'')+'<br>'+(w>=0?DATA.factions[w]:'주인 없음')+' · 유닛 약 '+cnt[fr*P+selP]*DATA.div+d}else document.getElementById('tip').style.display='none'}
const sl=document.getElementById('sl');sl.max=F-1;sl.oninput=()=>{fr=+sl.value;draw()};
const pb=document.getElementById('play');pb.onclick=()=>{playing=!playing;if(playing&&fr>=F-1)fr=0;pb.textContent=playing?'❚❚':'▶';pb.classList.toggle('on',playing)};
const sb=document.getElementById('spd');sb.onclick=()=>{speed=speed===1?2:speed===2?4:speed===4?.5:1;sb.textContent=speed+'x'};
document.getElementById('fit').onclick=()=>{fit();draw()};
document.getElementById('list').onclick=e=>{const r=e.target.closest('.row');if(!r)return;const f=+r.dataset.f;sel=sel===f?-1:f;draw()};
let acc=0,last=0;function loop(ts){if(playing){acc+=(ts-last)*speed;const step=250;while(acc>step){acc-=step;if(fr<F-1){fr++;sl.value=fr}else{playing=false;pb.textContent='▶';pb.classList.remove('on')}}draw()}last=ts;requestAnimationFrame(loop)}
// touch / mouse: drag to pan, pinch or wheel to zoom, tap to inspect
const pts=new Map();let moved=0,pd=0;
box.addEventListener('pointerdown',e=>{box.setPointerCapture(e.pointerId);pts.set(e.pointerId,[e.clientX,e.clientY]);moved=0;if(pts.size===2){const v=[...pts.values()];pd=Math.hypot(v[0][0]-v[1][0],v[0][1]-v[1][1])}});
box.addEventListener('pointermove',e=>{if(!pts.has(e.pointerId))return;const o=pts.get(e.pointerId),dx=e.clientX-o[0],dy=e.clientY-o[1];pts.set(e.pointerId,[e.clientX,e.clientY]);moved+=Math.abs(dx)+Math.abs(dy);
 if(pts.size===1){cam.x-=dx/cam.s;cam.y-=dy/cam.s}else if(pts.size===2){const v=[...pts.values()],d=Math.hypot(v[0][0]-v[1][0],v[0][1]-v[1][1]);if(pd>0)zoom(d/pd,(v[0][0]+v[1][0])/2,(v[0][1]+v[1][1])/2);pd=d}draw()});
function up(e){if(pts.has(e.pointerId)&&pts.size===1&&moved<8){const r=box.getBoundingClientRect(),x=Math.floor((e.clientX-r.left-box.clientWidth/2)/cam.s+cam.x),y=Math.floor((e.clientY-r.top-box.clientHeight/2)/cam.s+cam.y);
 const p=(x>=0&&y>=0&&x<GW&&y<GH)?cells[y*GW+x]:-1;selP=(p>=0&&land[p]&&p!==selP)?p:-1;draw()}pts.delete(e.pointerId);pd=0}
box.addEventListener('pointerup',up);box.addEventListener('pointercancel',up);
function zoom(k,px,py){const r=box.getBoundingClientRect(),mx=px-r.left-box.clientWidth/2,my=py-r.top-box.clientHeight/2,wx=mx/cam.s+cam.x,wy=my/cam.s+cam.y;cam.s=Math.max(.2,Math.min(24,cam.s*k));cam.x=wx-mx/cam.s;cam.y=wy-my/cam.s}
box.addEventListener('wheel',e=>{e.preventDefault();zoom(e.deltaY<0?1.2:1/1.2,e.clientX,e.clientY);draw()},{passive:false});
addEventListener('resize',()=>{resize()});fit();resize();requestAnimationFrame(loop);
</script></body></html>"""


def colors(n):
    import colorsys
    out = []
    for i in range(n):
        h = (i * 0.61803398875) % 1.0; s = 0.55 + 0.25 * ((i * 7) % 3) / 2; v = 0.62 + 0.3 * ((i * 5) % 4) / 3
        out.append([int(255 * c) for c in colorsys.hsv_to_rgb(h, s, v)])
    return out


def main():
    a = sys.argv[1:]; src, out = a[0], a[1]
    opt = lambda k, d: a[a.index(k) + 1] if k in a else d
    step = int(opt("--step", 12)); title = opt("--title", "Ridgeline"); models = opt("--models", None)
    h = R.read_header(src + ".rlr"); side = json.load(open(src + ".json")); sc = h["scene"]; gw, gh = sc["gw"], sc["gh"]; nf = len(h["factions"]); P = len(sc["provs"])
    with open(src + ".rlr", "rb") as f:
        f.seek(h["cells"][0]); cells = np.frombuffer(zlib.decompress(f.read(h["cells"][1])), np.int16).reshape(gh, gw)
    k = 2; small = cells[::k, ::k]                                   # half resolution is plenty for a phone
    pcell = np.full(P, -1)
    T = []; counts = []; changes = []; battles = []; events = []; prev = None; owner0 = None; evbuf = []; names = {}
    for t, ids, cols, prov, vis, shots, meta, G in R.frames(src + ".rlr"):
        m = json.loads(meta.tobytes() if hasattr(meta, "tobytes") else meta)
        for i, kind, text in m["ev"]:
            if kind == "fall": evbuf.append("%d일차: %s" % (t // 24 + 1, text))
        if t % step: continue
        own = prov[0].astype(np.int64) - 1
        x = (cols[0] + cols[1] * 256) // 20; y = (cols[2] + cols[3] * 256) // 20
        pid = cells[np.clip(y, 0, gh - 1), np.clip(x, 0, gw - 1)]; c = np.bincount(pid[pid >= 0], minlength=P)[:P]
        counts.append(np.minimum(255, (c + 3) // 4).astype(np.uint8))      # units / 4
        if prev is None: owner0 = own.tolist(); changes.append([])
        else:
            d = np.nonzero(own != prev)[0]; changes.append([int(v) for i in d for v in (i, own[i])])
        prev = own; T.append(int(t)); battles.append(sorted(set(int(b[0]) for b in m["battles"]))); events.append(sorted(set(evbuf))); evbuf = []
    sd = {s["t"]: s for s in side["side"]}; dep = []; st = []; att = won = 0; j = 0; ss = side["side"]
    for t in T:
        while j < len(ss) and ss[j]["t"] <= t: att += ss[j]["attacks"]; won += ss[j]["won"]; j += 1
        s = sd.get(t) or ss[min(len(ss) - 1, j - 1)]
        dep.append(s["depots"]); st.append(dict(pacts=s["pacts"], att=att, won=won, era=s.get("era"), ships=s.get("ships"), air=s.get("air"), wars=s.get("wars", 0),
                                                  sea=[[int(v) for v in k_.split(":")] + [c_] for k_, c_ in (s.get("sea") or {}).items()]))
    ml = models.split(",") if models else [""] * nf
    rivers = []
    try:
        sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
        from ridgeline import worldgen as W
        if gw * 420 == gh * 1152:
            deg = 360.0 / gw
            rivers = [[round(v, 1) for lat, lon in line for v in ((lon + 180.0) / deg / k, (W.LAT_N - lat) / deg / k)] for line in W.RIVERS.values()]
    except Exception: pass
    data = dict(rivers=rivers, gw=gw // k, gh=gh // k, cells=base64.b64encode(small.astype("<i2").tobytes()).decode(), factions=h["factions"],
                models=[("Opus" if "opus" in x else "Haiku" if "haiku" in x else x) for x in ml], colors=colors(nf),
                px=[round(p["cx"] / k, 1) for p in sc["provs"]], py=[round(p["cy"] / k, 1) for p in sc["provs"]], land=[int(p["terrain"] != "water") for p in sc["provs"]],
                names={str(p["id"]): p["name"] for p in sc["provs"] if p.get("name")}, capitals=sc["capitals"], cities=[p["id"] for p in sc["provs"] if p.get("city")], t=T, owner0=owner0, changes=changes,
                years=2000 if any(x.get("era") for x in st) else 0, counts=base64.b64encode(np.concatenate(counts).tobytes()).decode(), div=4, battles=battles, depots=dep, side=st, events=events)
    html = PAGE.replace("__TITLE__", title).replace("__DATA__", json.dumps(data, separators=(",", ":"), ensure_ascii=False))
    open(out, "w", encoding="utf-8").write(html); print("wrote", out, "%.2f MB" % (os.path.getsize(out) / 1e6), len(T), "frames")


if __name__ == "__main__":
    main()
