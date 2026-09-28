"""
行政区涂色 — 时间节点版
功能：缩放自适应线宽 + 前后对比度增强 + 时间分割（红蓝叠加）
修复：
  1. opacityFor(0)=1.0 导致无"节点后"经历的区县被红色实心覆盖 → 改为 layerOpacity，0段=该层完全透明
  2. 默认时间节点 = 今天，历史经历自动归为蓝色（节点前）
"""
import streamlit as st
import geopandas as gpd
import json
from datetime import date
from shapely.ops import unary_union

st.set_page_config(page_title="行政区涂色-时间轴", layout="wide")
st.title("🗺️ 行政区涂色（时间轴版）")

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

st.sidebar.markdown("📖 **操作说明**：点击区县 → 右侧面板添加经历")
st.sidebar.caption("红色=节点后(新)，蓝色=节点前(旧)，叠加=两段都有")

# 时间节点设置：默认今天
cutoff_date = st.sidebar.date_input("📅 时间分割节点", value=date.today())
cutoff_str = cutoff_date.isoformat() if cutoff_date else ""

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
all_names_json = json.dumps(all_names, ensure_ascii=False)

html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css">
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<script src="https://unpkg.com/xlsx@0.18.5/dist/xlsx.full.min.js"></script>
<style>
    body {{ margin: 0; font-family: sans-serif; display: flex; height: 100vh; }}
    #mapWrap {{ flex: 3; position: relative; }}
    #map {{ width: 100%; height: 100%; }}
    #panel {{
        flex: 1; min-width: 320px; max-width: 420px; padding: 16px;
        background: #f8f9fa; border-left: 1px solid #ddd; overflow-y: auto;
        display: flex; flex-direction: column; gap: 12px;
    }}
    #panel h3 {{ margin: 0 0 4px 0; font-size: 16px; }}
    #panel .sub {{ color: #666; font-size: 12px; }}
    #panel .exp-item {{
        background: white; padding: 8px 10px; border-radius: 6px;
        border: 1px solid #eee; display: flex; justify-content: space-between; gap: 8px;
        cursor: pointer; transition: background 0.15s;
    }}
    #panel .exp-item:hover {{ background: #fff8e1; }}
    #panel .exp-item.editing {{ background: #fff3cd; border-color: #ffc107; }}
    #panel .exp-item .del {{ color: #e74c3c; cursor: pointer; font-weight: bold; flex-shrink: 0; }}
    #panel .exp-item .tag {{
        display: inline-block; padding: 1px 6px; border-radius: 3px;
        font-size: 11px; margin-left: 6px; vertical-align: middle;
    }}
    #panel .tag.old {{ background: #dbeafe; color: #1e40af; }}
    #panel .tag.new {{ background: #fee2e2; color: #b91c1c; }}
    #panel input, #panel textarea, #panel button {{
        width: 100%; box-sizing: border-box; padding: 8px;
        border: 1px solid #ccc; border-radius: 6px; font-size: 13px;
    }}
    #panel textarea {{ resize: vertical; min-height: 60px; }}
    #panel button {{ background: #3498db; color: white; border: none; cursor: pointer; }}
    #panel button:hover {{ background: #2980b9; }}
    #toolbar {{
        position: absolute; top: 10px; right: 10px; z-index: 9999;
        background: white; padding: 8px 10px; border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 13px;
        display: flex; align-items: center; gap: 6px; flex-wrap: wrap; max-width: 600px;
    }}
    #toolbar button {{ border: none; padding: 6px 10px; border-radius: 4px; cursor: pointer; font-size: 12px; }}
    #legend {{
        position: absolute; bottom: 20px; left: 10px; z-index: 9999;
        background: white; padding: 10px 14px; border-radius: 6px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.2); font-size: 12px; line-height: 2;
    }}
    #legend .item {{ display: flex; align-items: center; gap: 6px; }}
    #legend .box {{ width: 20px; height: 12px; border-radius: 2px; }}
</style>
</head>
<body>
<div id="mapWrap">
    <div id="map"></div>
    <div id="toolbar">
        <button id="btnExportXlsx">📊 导出Excel</button>
        <button id="btnImportXlsx">📂 导入Excel</button>
        <input id="fileXlsx" type="file" accept=".xlsx,.xls" style="display:none">
        <button id="btnExportGeo">导出GeoJSON</button>
        <button id="btnLoadGeo">导入GeoJSON</button>
        <input id="fileGeo" type="file" accept=".geojson,.json" style="display:none">
        <button id="btnClear">清空</button>
    </div>
    <div id="legend">
        <div class="item"><span class="box" style="background:rgba(231,76,60,0.9)"></span>节点后 ≥4段</div>
        <div class="item"><span class="box" style="background:rgba(231,76,60,0.65)"></span>节点后 3段</div>
        <div class="item"><span class="box" style="background:rgba(231,76,60,0.4)"></span>节点后 2段</div>
        <div class="item"><span class="box" style="background:rgba(231,76,60,0.15)"></span>节点后 1段</div>
        <div class="item"><span class="box" style="background:rgba(59,130,246,0.7)"></span>节点前经历</div>
        <div class="item"><span class="box" style="background:rgba(147,51,234,0.6)"></span>前后都有(叠加)</div>
        <div class="item"><span class="line" style="border-top:3px solid #222;width:24px;"></span>省界</div>
        <div class="item"><span class="line" style="border-top:2px solid #666;width:24px;"></span>地界</div>
    </div>
</div>
<div id="panel">
    <div>
        <h3 id="pTitle">点击区县查看经历</h3>
        <div class="sub" id="pSub">尚未选择</div>
    </div>
    <div id="expList"></div>
    <div style="display:flex;flex-direction:column;gap:8px;">
        <input id="expDate" type="date" min="1950-01-01">
        <textarea id="expText" placeholder="经历描述"></textarea>
        <button id="btnAddExp">＋ 添加这段经历</button>
    </div>
</div>
<script>
var CUTOFF = {json.dumps(cutoff_str)};

var map = L.map('map').setView([{lat}, {lon}], 9);
L.tileLayer('https://{{s}}.basemaps.cartocdn.com/light_all/{{z}}/{{x}}/{{y}}.png', {{
    attribution: '&copy; OpenStreetMap & CartoDB'
}}).addTo(map);

// 创建两个 pane 用于叠加：蓝色底(z=200) + 红色面(z=210 在上)
map.createPane('bluePane'); map.getPane('bluePane').style.zIndex = 200;
map.createPane('redPane');  map.getPane('redPane').style.zIndex = 210;

var disGeoJSON = {dis_geojson};
var cityGeoJSON = {city_geojson};
var provGeoJSON = {prov_geojson};
var ALL_NAMES = {all_names_json};

var EXP_KEY = 'district_experiences_v2';
var experiences = JSON.parse(localStorage.getItem(EXP_KEY) || '{{}}');
var selectedName = null;
var lastDate = new Date().toISOString().slice(0, 10);
var editingIdx = null;

document.getElementById('expDate').value = lastDate;
document.getElementById('expDate').min = '1950-01-01';

// ===== 缩放自适应线宽 =====
function getLineWeights(zoom) {{
    if (zoom <= 7) return {{ prov: 1.5, city: 1.2, dis: 0.5 }};
    if (zoom <= 10) return {{ prov: 2.5, city: 2.0, dis: 0.8 }};
    return {{ prov: 3.5, city: 3.0, dis: 1.0 }};
}}
var currentWeights = getLineWeights(map.getZoom());

// 段数 → 透明度（面板/通用展示用；0段=1.0 保留"未访问灰色"语义）
function opacityFor(count) {{
    if (count === 0) return 1.0;
    if (count === 1) return 0.15;
    if (count === 2) return 0.4;
    if (count === 3) return 0.65;
    return 0.9;
}}

// 图层专用：0段 = 该层完全透明，让另一层/底色透出（修复全红的关键）
function layerOpacity(count) {{
    if (count === 0) return 0;
    if (count === 1) return 0.15;
    if (count === 2) return 0.4;
    if (count === 3) return 0.65;
    return 0.9;
}}

function styleFor(name) {{
    var n = (experiences[name] || []).length;
    return {{ fillColor: '#cccccc', fillOpacity: 1.0, color: '#999', weight: currentWeights.dis }};
}}

// 分离前后经历（date < CUTOFF → 蓝色/节点前；>= CUTOFF → 红色/节点后）
function splitExps(name) {{
    if (!CUTOFF) return {{ before: experiences[name] || [], after: [] }};
    var before = [], after = [];
    (experiences[name] || []).forEach(function(exp) {{
        if (exp.date >= CUTOFF) after.push(exp);
        else before.push(exp);
    }});
    return {{ before: before, after: after }};
}}

// ===== 图层 =====
var blueLayer = L.geoJSON(disGeoJSON, {{
    pane: 'bluePane',
    style: function(f) {{
        var split = splitExps(f.properties.name);
        return {{ fillColor: '#3b82f6', fillOpacity: layerOpacity(split.before.length), color: 'transparent', weight: 0 }};
    }},
    interactive: false
}}).addTo(map);

var redLayer = L.geoJSON(disGeoJSON, {{
    pane: 'redPane',
    style: function(f) {{
        var split = splitExps(f.properties.name);
        return {{ fillColor: '#e74c3c', fillOpacity: layerOpacity(split.after.length), color: '#999', weight: currentWeights.dis }};
    }},
    onEachFeature: function(feature, layer) {{
        layer.on('click', function(e) {{
            selectedName = feature.properties.name;
            cancelEdit();
            document.getElementById('expDate').value = lastDate;
            renderPanel();
        }});
    }}
}}).addTo(map);

// 边界层
var cityLayerLine = L.geoJSON(cityGeoJSON, {{
    style: function() {{ return {{ fill: false, color: '#666', weight: currentWeights.city, opacity: 0.85 }}; }},
    interactive: false
}}).addTo(map);

var provLayerLine = L.geoJSON(provGeoJSON, {{
    style: function() {{ return {{ fill: false, color: '#222', weight: currentWeights.prov, opacity: 0.95 }}; }},
    interactive: false
}}).addTo(map);

// ===== 缩放事件 =====
map.on('zoomend', function() {{
    var z = map.getZoom();
    currentWeights = getLineWeights(z);
    redLayer.setStyle(function(f) {{
        var split = splitExps(f.properties.name);
        return {{ fillColor: '#e74c3c', fillOpacity: layerOpacity(split.after.length), color: '#999', weight: currentWeights.dis }};
    }});
    cityLayerLine.setStyle(function() {{ return {{ fill: false, color: '#666', weight: currentWeights.city, opacity: 0.85 }}; }});
    provLayerLine.setStyle(function() {{ return {{ fill: false, color: '#222', weight: currentWeights.prov, opacity: 0.95 }}; }});
}});

// ===== 面板 =====
function sortExps(name) {{
    (experiences[name] || []).sort(function(a, b) {{ return a.date < b.date ? -1 : 1; }});
}}

function cancelEdit() {{
    editingIdx = null;
    document.getElementById('expDate').value = lastDate;
    document.getElementById('expText').value = '';
    document.getElementById('btnAddExp').textContent = '＋ 添加这段经历';
}}

function renderPanel() {{
    var titleEl = document.getElementById('pTitle');
    var subEl   = document.getElementById('pSub');
    var listEl  = document.getElementById('expList');
    if (!selectedName) {{
        titleEl.textContent = '点击区县查看经历';
        subEl.textContent = '尚未选择';
        listEl.innerHTML = '';
        return;
    }}
    var feat = disGeoJSON.features.find(function(f) {{ return f.properties.name === selectedName; }});
    var ct = feat ? feat.properties.ct_name : null;
    var exps = experiences[selectedName] || [];
    var split = splitExps(selectedName);
    titleEl.textContent = selectedName;
    var tagInfo = '';
    if (CUTOFF) {{
        tagInfo = ' | 节点前 ' + split.before.length + ' 段 / 节点后 ' + split.after.length + ' 段';
    }}
    subEl.textContent = (ct ? '所属地市：' + ct + '  ·  ' : '') + '总经历：' + exps.length + tagInfo;
    listEl.innerHTML = '';
    exps.forEach(function(exp, idx) {{
        var isNew = !CUTOFF || exp.date >= CUTOFF;
        var tag = isNew
            ? '<span class="tag new">新</span>'
            : '<span class="tag old">旧</span>';
        var item = document.createElement('div');
        item.className = 'exp-item' + (idx === editingIdx ? ' editing' : '');
        item.innerHTML = '<div><b>' + exp.date + '</b>' + tag + '<br>' + (exp.text || '(无描述)') + '</div>'
                      + '<span class="del" data-idx="' + idx + '">✕</span>';
        item.onclick = function(e) {{
            if (e.target.classList.contains('del')) return;
            editingIdx = idx;
            document.getElementById('expDate').value = exp.date;
            document.getElementById('expText').value = exp.text || '';
            document.getElementById('btnAddExp').textContent = '💾 保存修改';
            renderPanel();
        }};
        listEl.appendChild(item);
    }});
    listEl.querySelectorAll('.del').forEach(function(el) {{
        el.onclick = function(e) {{
            e.stopPropagation();
            var idx = parseInt(el.getAttribute('data-idx'));
            experiences[selectedName].splice(idx, 1);
            if (experiences[selectedName].length === 0) delete experiences[selectedName];
            if (editingIdx === idx) cancelEdit();
            else if (editingIdx !== null && idx < editingIdx) editingIdx--;
            saveAndUpdate();
        }};
    }});
}}

document.getElementById('btnAddExp').onclick = function() {{
    if (!selectedName) {{ alert('请先在地图上点击一个区县'); return; }}
    var d = document.getElementById('expDate').value;
    var t = document.getElementById('expText').value.trim();
    if (!d) {{ alert('请选择日期'); return; }}
    if (!experiences[selectedName]) experiences[selectedName] = [];
    if (editingIdx !== null && editingIdx >= 0) {{
        experiences[selectedName][editingIdx] = {{ date: d, text: t }};
        sortExps(selectedName);
        cancelEdit();
    }} else {{
        experiences[selectedName].push({{ date: d, text: t }});
        sortExps(selectedName);
        lastDate = d;
    }}
    document.getElementById('expText').value = '';
    saveAndUpdate();
}};

function saveAndUpdate() {{
    localStorage.setItem(EXP_KEY, JSON.stringify(experiences));
    blueLayer.setStyle(function(f) {{
        var split = splitExps(f.properties.name);
        return {{ fillColor: '#3b82f6', fillOpacity: layerOpacity(split.before.length), color: 'transparent', weight: 0 }};
    }});
    redLayer.setStyle(function(f) {{
        var split = splitExps(f.properties.name);
        return {{ fillColor: '#e74c3c', fillOpacity: layerOpacity(split.after.length), color: '#999', weight: currentWeights.dis }};
    }});
    renderPanel();
}}
renderPanel();

// ===== 导出 Excel =====
document.getElementById('btnExportXlsx').onclick = function() {{
    var maxExp = 0;
    ALL_NAMES.forEach(function(n) {{ var len = (experiences[n] || []).length; if (len > maxExp) maxExp = len; }});
    var headers = ['区县名称', '所属地市', '经历段数'];
    if (CUTOFF) headers.push('节点前段数', '节点后段数');
    for (var i = 1; i <= maxExp; i++) {{ headers.push('经历' + i + '日期'); headers.push('经历' + i + '描述'); }}
    var rows = [headers];
    ALL_NAMES.forEach(function(n) {{
        var feat = disGeoJSON.features.find(function(f) {{ return f.properties.name === n; }});
        var ct = feat ? feat.properties.ct_name : '';
        var exps = experiences[n] || [];
        var split = splitExps(n);
        var row = [n, ct, exps.length];
        if (CUTOFF) row.push(split.before.length, split.after.length);
        for (var i = 0; i < maxExp; i++) {{
            if (i < exps.length) {{ row.push(exps[i].date); row.push(exps[i].text); }}
            else {{ row.push(''); row.push(''); }}
        }}
        rows.push(row);
    }});
    if (typeof XLSX !== 'undefined') {{
        var ws = XLSX.utils.aoa_to_sheet(rows);
        var wb = XLSX.utils.book_new();
        XLSX.utils.book_append_sheet(wb, ws, '经历记录');
        XLSX.writeFile(wb, '经历记录.xlsx');
    }} else {{
        alert('SheetJS未加载，请用CSV');
    }}
}};

// ===== 导入 Excel =====
document.getElementById('btnImportXlsx').onclick = function() {{ document.getElementById('fileXlsx').click(); }};
document.getElementById('fileXlsx').addEventListener('change', function(e) {{
    var f = e.target.files[0]; if (!f) return;
    var reader = new FileReader();
    reader.onload = function(ev) {{
        try {{
            var wb = XLSX.read(ev.target.result, {{type:'array'}});
            var ws = wb.Sheets[wb.SheetNames[0]];
            var data = XLSX.utils.sheet_to_json(ws, {{header:1}});
            if (data.length < 2) {{ alert('文件为空'); return; }}
            var header = data[0];
            var nameIdx = header.findIndex(function(h) {{ return String(h).indexOf('区县') >= 0; }});
            if (nameIdx < 0) nameIdx = 0;
            var imported = 0;
            for (var r = 1; r < data.length; r++) {{
                var row = data[r];
                var nm = row[nameIdx]; if (!nm) continue;
                var exps = [];
                for (var c = nameIdx + 3; c < row.length; c += 2) {{
                    if (!row[c]) break;
                    exps.push({{ date: String(row[c]).slice(0,10), text: row[c+1] || '' }});
                }}
                if (exps.length > 0) {{ experiences[String(nm)] = exps; imported++; }}
            }}
            ALL_NAMES.forEach(function(n) {{ sortExps(n); }});
            saveAndUpdate();
            alert('已导入 ' + imported + ' 个区县');
        }} catch(err) {{ alert('错误：' + err.message); }}
    }};
    reader.readAsArrayBuffer(f);
    e.target.value = '';
}});

// ===== GeoJSON =====
document.getElementById('btnExportGeo').onclick = function() {{
    var out = disGeoJSON.features.map(function(f) {{
        var n = f.properties.name;
        var feat = JSON.parse(JSON.stringify(f));
        feat.properties.experiences = experiences[n] || [];
        return feat;
    }});
    var blob = new Blob([JSON.stringify({{type:'FeatureCollection',features:out}})], {{type:'application/geo+json'}});
    var a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = '经历记录.geojson'; a.click();
}};
document.getElementById('btnLoadGeo').onclick = function() {{ document.getElementById('fileGeo').click(); }};
document.getElementById('fileGeo').addEventListener('change', function(e) {{
    var f = e.target.files[0]; if (!f) return;
    var r = new FileReader();
    r.onload = function(ev) {{
        try {{
            var data = JSON.parse(ev.target.result);
            (data.features || []).forEach(function(ft) {{
                var p = ft.properties || {{}}, n = p.name || p.dt_name;
                if (n && Array.isArray(p.experiences)) {{ experiences[n] = p.experiences; sortExps(n); }}
            }});
            saveAndUpdate(); alert('已导入');
        }} catch(err) {{ alert('错误：' + err.message); }}
    }};
    r.readAsText(f);
}});

document.getElementById('btnClear').onclick = function() {{
    if (!confirm('确定清空所有经历记录？')) return;
    experiences = {{}}; selectedName = null; editingIdx = null;
    localStorage.removeItem(EXP_KEY);
    saveAndUpdate();
}};
</script>
</body>
</html>
"""

col_map, col_ctrl = st.columns([4, 1])
with col_map:
    st.components.v1.html(html, height=1260, width=None)
with col_ctrl:
    st.subheader("使用说明")
    st.markdown("""
**时间节点功能**
- 侧边栏设置分割日期（**默认为今天**）
- 红色 = 节点后（新经历）
- 蓝色 = 节点前（旧经历）
- 紫色叠加 = 前后都有

**缩放自适应**
- 缩小看全国：线细
- 放大看区县：线粗

**颜色阶梯**
- 1段 15% → 2段 40% → 3段 65% → ≥4段 90%

**操作**
- 点击经历可编辑
- 导出/导入 Excel & GeoJSON
    """)
