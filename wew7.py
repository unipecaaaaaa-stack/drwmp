"""
行政区涂色 — 完整版
================================================
功能清单（按添加顺序）：
1. 三层边界：省界(3.5px黑)/地界(3px灰)/县界(1px浅灰)，县界可点击涂色
2. 颜色选择器在前端工具栏（不触发 Streamlit rerun）
3. 悬浮 tooltip：区县名 + 所属地市 + 涂色进度 + 到访时间
4. 涂色进度实时计算（前端 JS，按地级市分组）
5. 日期选择器在前端（不触发 rerun），范围 1950-01-01 起
6. 记录第一次到访时间（firstVisit，每次点击覆盖写入）
7. 记录最近一次到访时间（lastVisit，每次点击覆盖写入）
8. 下拉菜单切换 tooltip 显示"第一次/最近一次"到访时间
9. 导出对照表含：区县,是否涂色,颜色分类,第一次到访,最近一次到访
10. 导入对照表/GeoJSON 时回填到访时间；清空时一并清除
"""
import streamlit as st
import geopandas as gpd
import json
from shapely.ops import unary_union

st.set_page_config(page_title="行政区涂色", layout="wide")
st.title("🗺️ 行政区涂色（分层边界）")

@st.cache_data
def load_gdf(path):
    g = gpd.read_file(path, encoding="utf-8")
    if g.crs != "EPSG:4326":
        g = g.to_crs("EPSG:4326")
    g = g[g.geometry.notna()].copy()
    return g

prov_gdf = load_gdf("province.shp")
city_gdf = load_gdf("city.shp")
dis_gdf  = load_gdf("district.shp").rename(columns={"dt_name": "name"})

st.sidebar.markdown("🎨 **涂色/日期/显示模式**：均在地图右上角工具栏选择")
st.sidebar.caption("日期范围：1950-01-01 起")

@st.cache_data
def build_county(_gdf):
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature",
         "properties": {"name": r["name"], "ct_name": r.get("ct_name", "")},
         "geometry": r.geometry.__geo_interface__}
        for _, r in _gdf.iterrows()
    ]})

@st.cache_data
def build_merged(_gdf, group_field):
    grouped = _gdf.groupby(group_field)["geometry"].apply(lambda s: unary_union(list(s)))
    return json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {}, "geometry": geom.__geo_interface__}
        for _, geom in grouped.items() if geom and not geom.is_empty
    ]})

prov_geojson = build_merged(prov_gdf, "pr_name")
city_geojson = build_merged(city_gdf, "ct_name")
dis_geojson  = build_county(dis_gdf)

lat = dis_gdf.geometry.centroid.y.mean()
lon = dis_gdf.geometry.centroid.x.mean()
all_names = dis_gdf["name"].dropna().unique().tolist()

html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
    #map {{ width: 100%; height: 86vh; margin: 0; padding: 0; }}
    body {{ margin: 0; font-family: sans-serif; }}
    #toolbar {{
        position: absolute; top: 10px; right: 10px; z-index: 9999;
        background: white; padding: 8px 10px; border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 13px;
        display: flex; align-items: center; gap: 6px; flex-wrap: wrap; max-width: 640px;
    }}
    #toolbar button {{ border: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }}
    #toolbar select, #toolbar input[type="date"] {{
        font-size: 12px; padding: 4px 6px; border-radius: 4px; border: 1px solid #ccc;
    }}
    #btnExport {{ background: #3498db; color: white; }}
    #btnTable {{ background: #2ecc71; color: white; }}
    #btnLoadGeo {{ background: #9b59b6; color: white; }}
    #btnLoadCsv {{ background: #e67e22; color: white; }}
    #btnClear {{ background: #e74c3c; color: white; }}
    #countLabel {{ font-weight: bold; color: #333; margin-right: 4px; }}
    .fileinp {{ display: none; }}
    #legend {{
        position: absolute; bottom: 20px; left: 10px; z-index: 9999;
        background: white; padding: 8px 12px; border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 12px; line-height: 1.8;
    }}
    #legend .item {{ display: flex; align-items: center; gap: 6px; }}
    #legend .line {{ width: 24px; height: 0; }}
</style>
</head>
<body>
<div id="map"></div>
<div id="toolbar">
    <span id="countLabel">已涂色：0</span>
    <select id="colorPicker">
        <option value="#e74c3c">红色</option>
        <option value="#3498db">蓝色</option>
        <option value="#2ecc71">绿色</option>
        <option value="#f1c40f">黄色</option>
        <option value="#e67e22">橙色</option>
        <option value="#9b59b6">紫色</option>
        <option value="#cccccc">未分类</option>
    </select>
    <input id="datePicker" type="date" min="1950-01-01" value="">
    <select id="visitMode">
        <option value="first">显示：第一次到访</option>
        <option value="last">显示：最近一次到访</option>
    </select>
    <button id="btnExport">导出GeoJSON</button>
    <button id="btnTable">导出对照表</button>
    <button id="btnLoadGeo">加载GeoJSON</button>
    <button id="btnLoadCsv">导入对照表</button>
    <input id="fileGeo" class="fileinp" type="file" accept=".geojson,.json">
    <input id="fileCsv" class="fileinp" type="file" accept=".csv">
    <button id="btnClear">清空</button>
</div>
<div id="legend">
    <div class="item"><span class="line" style="border-top:3.5px solid #222"></span> 省界</div>
    <div class="item"><span class="line" style="border-top:3px solid #666"></span> 地界</div>
    <div class="item"><span class="line" style="border-top:1px solid #999"></span> 县界</div>
</div>
<script>
var map = L.map('map').setView([{lat}, {lon}], 9);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap & CartoDB'
}}).addTo(map);

var disGeoJSON = {dis_geojson};
var cityGeoJSON = {city_geojson};
var provGeoJSON = {prov_geojson};

var curColor = '#e74c3c';
var STORAGE_KEY = 'district_colored_v1';
var FIRST_KEY  = 'district_firstVisit_v1';
var LAST_KEY   = 'district_lastVisit_v1';
var HEX2NAME = {{
    '#e74c3c':'红色','#3498db':'蓝色','#2ecc71':'绿色',
    '#f1c40f':'黄色','#e67e22':'橙色','#9b59b6':'紫色','#cccccc':'未分类'
}};
var ALL_NAMES = {json.dumps(all_names)};
var colored  = JSON.parse(localStorage.getItem(STORAGE_KEY) || '{{}}');
var firstVis = JSON.parse(localStorage.getItem(FIRST_KEY) || '{{}}');
var lastVis  = JSON.parse(localStorage.getItem(LAST_KEY) || '{{}}');

var dateInput = document.getElementById('datePicker');
dateInput.value = new Date().toISOString().slice(0, 10);
dateInput.min = '1950-01-01';
dateInput.max = new Date().toISOString().slice(0, 10);

var visitMode = 'first';
document.getElementById('visitMode').onchange = function(e) {{ visitMode = e.target.value; }};
document.getElementById('colorPicker').onchange = function(e) {{ curColor = e.target.value; }};

var cityCountyMap = {{}};
disGeoJSON.features.forEach(function(f) {{
    var ct = f.properties.ct_name || "未知";
    if (!cityCountyMap[ct]) cityCountyMap[ct] = [];
    cityCountyMap[ct].push(f.properties.name);
}});

function cityProgress(ctName) {{
    var counties = cityCountyMap[ctName] || [];
    var done = 0;
    counties.forEach(function(n) {{ if (colored[n]) done++; }});
    return done + '/' + counties.length;
}}

function getVisitText(name) {{
    if (visitMode === 'last') {{
        return lastVis[name] ? '最近到访：' + lastVis[name] : '';
    }}
    return firstVis[name] ? '首次到访：' + firstVis[name] : '';
}}

var geoLayer = L.geoJSON(disGeoJSON, {{
    style: function(f) {{
        return {{
            fillColor: colored[f.properties.name] || '#cccccc',
            fillOpacity: 1, color: '#999', weight: 1
        }};
    }},
    onEachFeature: function(feature, layer) {{
        layer.bindTooltip(function(l) {{
            var name = l.feature.properties.name;
            var ct = l.feature.properties.ct_name || "未知";
            var prog = cityProgress(ct);
            var parts = prog.split('/');
            var allDone = parts[0] == parts[1];
            var vt = getVisitText(name);
            return '<div style="font-size:13px;">' +
                '<b>' + name + '</b><br>' +
                '所属地市：' + ct + '<br>' +
                '涂色进度：<span style="font-weight:bold;color:' + (allDone ? '#27ae60' : '#e74c3c') + '">' + prog + '</span>' +
                (allDone ? ' ✅' : '') + (vt ? '<br>' + vt : '') +
                '</div>';
        }}, {{ sticky: true, direction: 'top' }});

        layer.on('click', function(e) {{
            var name = feature.properties.name;
            var d = dateInput.value || new Date().toISOString().slice(0, 10);
            colored[name] = curColor;
            firstVis[name] = d;   // 每次点击覆盖写入
            lastVis[name] = d;    // 每次点击覆盖写入
            layer.setStyle({{ fillColor: curColor, color: '#333', weight: 2, fillOpacity: 1 }});
            saveAndUpdate();
        }});
    }}
}}).addTo(map);

L.geoJSON(cityGeoJSON, {{
    style: function() {{ return {{ fill: false, color: '#666', weight: 3, opacity: 0.85 }}; }},
    interactive: false
}}).addTo(map);

L.geoJSON(provGeoJSON, {{
    style: function() {{ return {{ fill: false, color: '#222', weight: 3.5, opacity: 0.95 }}; }},
    interactive: false
}}).addTo(map);

function saveAndUpdate() {{
    localStorage.setItem(STORAGE_KEY, JSON.stringify(colored));
    localStorage.setItem(FIRST_KEY, JSON.stringify(firstVis));
    localStorage.setItem(LAST_KEY, JSON.stringify(lastVis));
    document.getElementById('countLabel').textContent = '已涂色：' + Object.keys(colored).length;
}}
function applyColored() {{
    geoLayer.eachLayer(function(l) {{
        if (l.feature && l.feature.properties) {{
            var name = l.feature.properties.name;
            if (colored[name]) l.setStyle({{ fillColor: colored[name], color: '#333', weight: 1, fillOpacity: 1 }});
        }}
    }});
}}
saveAndUpdate();

function parseCSV(text) {{
    if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
    return text.split(/\\r?\\n/).filter(function(l){{return l.trim()!=='';}}).map(function(line){{
        var p=line.split(',');
        return {{name:(p[0]||'').trim(),cat:(p[2]||'').trim(),first:(p[3]||'').trim(),last:(p[4]||'').trim()}};
    }});
}}
function hexFromCategory(cat){{
    if(!cat) return null;
    var m={{'红色':'#e74c3c','蓝色':'#3498db','绿色':'#2ecc71','黄色':'#f1c40f','橙色':'#e67e22','紫色':'#9b59b6','未分类':'#cccccc'}};
    return m[cat] || (cat.indexOf('#')===0 ? cat : null);
}}

document.getElementById('btnLoadCsv').addEventListener('click', function(){{document.getElementById('fileCsv').click();}});
document.getElementById('fileCsv').addEventListener('change', function(e){{
    var f=e.target.files[0]; if(!f) return;
    var r=new FileReader(); r.onload=function(ev){{
        try{{
            var rows=parseCSV(ev.target.result), cnt=0, skip=0;
            rows.forEach(function(row,i){{
                if(i===0) return;
                var hex=hexFromCategory(row.cat);
                if(!hex){{skip++;return;}}
                colored[row.name]=hex;
                if(row.first) firstVis[row.name]=row.first;
                if(row.last)  lastVis[row.name]=row.last;
                cnt++;
            }});
            localStorage.setItem(STORAGE_KEY, JSON.stringify(colored));
            localStorage.setItem(FIRST_KEY, JSON.stringify(firstVis));
            localStorage.setItem(LAST_KEY, JSON.stringify(lastVis));
            applyColored(); saveAndUpdate();
            alert('导入完成：成功 '+cnt+' 条'+(skip?'，跳过 '+skip+' 条':''));
        }}catch(err){{alert('错误：'+err.message);}}
    }}; r.readAsText(f);
}});

document.getElementById('btnLoadGeo').addEventListener('click', function(){{document.getElementById('fileGeo').click();}});
document.getElementById('fileGeo').addEventListener('change', function(e){{
    var f=e.target.files[0]; if(!f) return;
    var r=new FileReader(); r.onload=function(ev){{
        try{{
            var data=JSON.parse(ev.target.result), feats=data.features||[], cnt=0;
            feats.forEach(function(ft){{
                var p=ft.properties||{{}}, n=p.name||p.dt_name, c=p.color;
                if(n&&c){{colored[n]=c;cnt++;}}
                if(n&&p.firstVisit) firstVis[n]=p.firstVisit;
                if(n&&p.lastVisit)  lastVis[n]=p.lastVisit;
            }});
            localStorage.setItem(STORAGE_KEY, JSON.stringify(colored));
            localStorage.setItem(FIRST_KEY, JSON.stringify(firstVis));
            localStorage.setItem(LAST_KEY, JSON.stringify(lastVis));
            applyColored(); saveAndUpdate();
            alert('已加载 '+cnt+' 条');
        }}catch(err){{alert('错误：'+err.message);}}
    }}; r.readAsText(f);
}});

document.getElementById('btnExport').addEventListener('click', function(){{
    var out=disGeoJSON.features.map(function(f){{
        var n=f.properties.name, feat=JSON.parse(JSON.stringify(f));
        feat.properties.color=colored[n]||'#cccccc';
        feat.properties.firstVisit=firstVis[n]||'';
        feat.properties.lastVisit=lastVis[n]||'';
        return feat;
    }});
    var blob=new Blob([JSON.stringify({{type:'FeatureCollection',features:out}})],{{type:'application/geo+json'}});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='district_colored.geojson'; a.click();
}});

document.getElementById('btnTable').addEventListener('click', function(){{
    var lines=['区县名称,是否涂色,颜色分类,第一次到访时间,最近一次到访时间'];
    ALL_NAMES.forEach(function(n){{
        var cat=colored[n]?HEX2NAME[colored[n]]||'自定义':'未涂色';
        var yn=colored[n]?'是':'否';
        var fv=firstVis[n]||'';
        var lv=lastVis[n]||'';
        lines.push(n+','+yn+','+cat+','+fv+','+lv);
    }});
    var blob=new Blob(['\\uFEFF'+lines.join('\\n')],{{type:'text/csv;charset=utf-8'}});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download='涂色对照表.csv'; a.click();
}});

document.getElementById('btnClear').addEventListener('click', function(){{
    if(!confirm('确定清空所有涂色及到访记录？')) return;
    colored={{}}; firstVis={{}}; lastVis={{}};
    localStorage.removeItem(STORAGE_KEY);
    localStorage.removeItem(FIRST_KEY);
    localStorage.removeItem(LAST_KEY);
    geoLayer.eachLayer(function(l){{l.setStyle({{fillColor:'#cccccc',color:'#999',weight:1,fillOpacity:1}});}});
    saveAndUpdate();
}});
</script>
</body>
</html>
"""

col_map, col_ctrl = st.columns([4, 1])
with col_map:
    st.components.v1.html(html, height=740, width=900)
with col_ctrl:
    st.subheader("操作说明")
    st.markdown("""
**地图右上角工具栏**
- 📅 日期选择器：选到访时间（范围 1950 年起，默认今天）
- 🔽 颜色下拉：选当前涂色
- 🔽 显示模式：切换悬浮提示里的"第一次/最近一次"到访
- 📥 导出GeoJSON / 📊 导出对照表
- 📂 加载GeoJSON / 📄 导入对照表
- 🗑️ 清空

**悬浮提示**
- 区县名 + 所属地市 + 涂色进度 + 当前模式的到访时间

**图例（左下角）**
- 省界 3.5px 黑 / 地界 3px 灰 / 县界 1px 浅灰
    """)
    st.success("日期选择器在前端，切换不触发 rerun\\n两次到访时间每次点击都覆盖写入")