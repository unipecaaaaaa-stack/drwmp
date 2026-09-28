import streamlit as st
import geopandas as gpd
import pandas as pd
import json
from datetime import datetime
import warnings
import io

warnings.filterwarnings("ignore")

st.set_page_config(page_title="行政区涂色 ribbon3", layout="wide")

st.write("### 🎨 ribbon3 — 导入导出 + 降精度优化")

# ========== 1. shp 读取（固定路径，后续可改上传） ==========
shp_path = r"C:\Users\zhangweibo\Documents\ChinaAdminDivisonSHP\new\district.shp"

try:
    dis_gdf = gpd.read_file(shp_path)
    st.write(f"✅ shp 读取成功，原始 {len(dis_gdf)} 条")
except Exception as e:
    st.error(f"❌ shp 读取失败: {e}")
    st.stop()

# ========== 2. 几何优化：make_valid + simplify + 降精度 ==========
st.write("### 🔧 几何优化")

with st.spinner("正在优化几何（make_valid → simplify 11m → 降精度 4位）..."):
    try:
        # Step 1: 修复无效几何
        dis_gdf["geometry"] = dis_gdf["geometry"].make_valid()
        valid_count = dis_gdf.geometry.is_valid.sum()
        
        # Step 2: simplify 11m (0.0001° ≈ 11m)
        dis_gdf["geometry"] = dis_gdf["geometry"].simplify(
            tolerance=0.0001, preserve_topology=True
        )
        
        # Step 3: 降精度到 4 位小数（≈11m）
        dis_gdf["geometry"] = dis_gdf["geometry"].set_precision(1e-4)
        
        # Step 4: 过滤空/无效
        before = len(dis_gdf)
        dis_gdf = dis_gdf[dis_gdf.geometry.is_valid & ~dis_gdf.geometry.is_empty]
        after = len(dis_gdf)
        
        st.write(f"✅ 几何优化完成: {before} → {after} 个有效要素")
        st.write(f"   make_valid: {valid_count}/{before} 原本有效")
        st.write(f"   simplify: tolerance=0.0001° (≈11m)")
        st.write(f"   set_precision: 4位小数")
    except Exception as e:
        st.error(f"❌ 几何优化失败: {e}")
        st.stop()

# ========== 3. 确保 name 列 ==========
if "name" not in dis_gdf.columns:
    for col in dis_gdf.columns:
        if "name" in col.lower() or "dt_name" in col.lower():
            dis_gdf = dis_gdf.rename(columns={col: "name"})
            st.write(f"✅ 重命名列 '{col}' → 'name'")
            break

if "name" not in dis_gdf.columns:
    st.error(f"❌ 找不到 name 列！现有列: {list(dis_gdf.columns)}")
    st.stop()

# ========== 4. Excel 导入（上传） ==========
st.write("### 📂 数据导入")

uploaded_file = st.file_uploader("上传经历 Excel 文件", type=["xlsx", "xls"])

experiences = {}

if uploaded_file is not None:
    try:
        df = pd.read_excel(uploaded_file)
        st.write(f"✅ Excel 读取成功，共 {len(df)} 条")
        st.write(f"   列名: {list(df.columns)}")
        
        def extract_year(val):
            if pd.isna(val) or val is None:
                return None
            s = str(val).strip()
            for sep in ["-", "/", "."]:
                if sep in s:
                    try:
                        return int(s.split(sep)[0])
                    except:
                        pass
            try:
                return int(s[:4])
            except:
                return None
        
        if "经历1日期" in df.columns:
            for _, row in df.iterrows():
                name = row.get("姓名") or row.get("name")
                date_val = row.get("经历1日期")
                year = extract_year(date_val)
                if name and year:
                    experiences[str(name)] = year
            
            st.write(f"✅ 经历数据解析: {len(experiences)} 条有效记录")
            if experiences:
                years = list(experiences.values())
                st.write(f"   数据年份范围: {min(years)} ~ {max(years)}")
        else:
            st.warning("⚠️ Excel 中未找到 '经历1日期' 列，将全部显示灰色")
            
    except Exception as e:
        st.error(f"❌ Excel 解析失败: {e}")
else:
    st.info("💡 未上传 Excel，所有区县将显示灰色（可先浏览地图）")

# ========== 5. 侧边栏参数 ==========
st.sidebar.header("时间轴设置")

# 自动计算年份范围（如果有数据）
if experiences:
    data_years = list(experiences.values())
    auto_min = min(data_years)
    auto_max = max(data_years)
else:
    auto_min = 2015
    auto_max = 2025

year_min_input = st.sidebar.number_input("起始年份", value=auto_min, step=1)
year_max_input = st.sidebar.number_input("结束年份", value=max(auto_max, auto_min + 1), step=1)

# 保底
if year_max_input - year_min_input < 1:
    year_max_input = year_min_input + 1
    st.sidebar.warning("⚠️ 起止年份相同，已自动+1")

hue_start = st.sidebar.selectbox("起始色相 (0=红,120=绿,240=蓝)", [0, 60, 120, 180, 240, 300], index=0)
hue_end = st.sidebar.selectbox("结束色相", [0, 60, 120, 180, 240, 300], index=4)

# ========== 6. 中心点 ==========
bounds = dis_gdf.total_bounds
lon = (bounds[0] + bounds[2]) / 2
lat = (bounds[1] + bounds[3]) / 2
st.write(f"✅ 中心点: lat={lat:.4f}, lon={lon:.4f}")

# ========== 7. 构建 GeoJSON ==========
try:
    geojson_data = json.loads(dis_gdf.to_json())
    st.write(f"✅ GeoJSON 构建成功，共 {len(geojson_data['features'])} 个要素")
except Exception as e:
    st.error(f"❌ GeoJSON 构建失败: {e}")
    st.stop()

# ========== 8. 导出功能 ==========
st.write("### 📤 导出")

col1, col2 = st.columns(2)

with col1:
    if st.button("导出 GeoJSON（带颜色信息）"):
        # 给每个 feature 加上 color 属性
        for f in geojson_data["features"]:
            name = f["properties"].get("name")
            year = experiences.get(name)
            if year:
                t = (year - year_min_input) / (year_max_input - year_min_input)
                t = max(0, min(1, t))
                hue = hue_start + t * (hue_end - hue_start)
                f["properties"]["_color"] = f"hsl({hue:.0f}, 100%, 50%)"
                f["properties"]["_year"] = year
            else:
                f["properties"]["_color"] = "#cccccc"
                f["properties"]["_year"] = None
        
        export_geojson = json.dumps(geojson_data, ensure_ascii=False, indent=2)
        st.download_button(
            label="⬇️ 下载 colored.geojson",
            data=export_geojson,
            file_name="colored_districts.geojson",
            mime="application/json"
        )

with col2:
    if st.button("导出 Excel（回填年份）"):
        if experiences:
            export_df = pd.DataFrame([
                {"区县名称": k, "经历年份": v} for k, v in experiences.items()
            ])
            # 也加上 shp 里所有区县（无经历的标空）
            all_names = [f["properties"].get("name") for f in geojson_data["features"]]
            for name in all_names:
                if name not in experiences:
                    export_df = pd.concat([export_df, pd.DataFrame([{"区县名称": name, "经历年份": None}])], ignore_index=True)
            
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="openpyxl") as writer:
                export_df.to_excel(writer, index=False, sheet_name="经历数据")
            
            st.download_button(
                label="⬇️ 下载 经历数据.xlsx",
                data=output.getvalue(),
                file_name="经历数据_导出.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            st.warning("无经历数据可导出")

# ========== 9. 生成 HTML ==========
geojson_str = json.dumps(geojson_data, ensure_ascii=False)
experiences_str = json.dumps(experiences, ensure_ascii=False)

html = f"""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<title>ribbon3</title>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
html, body, #map {{ margin:0; padding:0; height:100%; width:100%; }}
#map {{ height:100vh; }}
#timingPanel {{
    position:fixed; top:10px; right:10px; z-index:9999;
    background:rgba(0,0,0,0.8); color:#0f0;
    padding:10px 14px; border-radius:6px;
    font:bold 14px/1.4 monospace;
    display:none;
}}
#colorbar {{
    position:fixed; bottom:30px; left:50%; transform:translateX(-50%);
    z-index:9999; background:rgba(255,255,255,0.95);
    padding:8px 16px; border-radius:6px; font:12px sans-serif;
    display:flex; align-items:center; gap:8px;
}}
#colorbar .gradient {{
    width:200px; height:14px; border-radius:3px;
    background: linear-gradient(to right, hsl({hue_start},100%,50%), hsl({hue_end},100%,50%));
}}
</style>
</head>
<body>

<div id="map"></div>
<div id="timingPanel">渲染中...</div>
<div id="colorbar">
    <span>{year_min_input}</span>
    <div class="gradient"></div>
    <span>{year_max_input}</span>
</div>

<script>
var DEBUG = true;
function dbg(msg) {{ if(DEBUG) console.log("[ribbon3] " + msg); }}

dbg("开始初始化地图");

var map = L.map('map', {{
    preferCanvas: true,
    zoomControl: false
}}).setView([{lat}, {lon}], 9);

L.control.zoom({{ position: 'topright' }});

dbg("setView done");

L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18,
    attribution: '© OpenStreetMap'
}}).addTo(map);

dbg("瓦片加载完成");

var geojsonData = {geojson_str};
var experiences = {experiences_str};
var YEAR_MIN = {year_min_input};
var YEAR_MAX = {year_max_input};
var HUE_START = {hue_start};
var HUE_END = {hue_end};

dbg("数据: features=" + geojsonData.features.length + ", exp=" + Object.keys(experiences).length);

function yearToColor(year) {{
    if (!year) return "#cccccc";
    var t = (year - YEAR_MIN) / (YEAR_MAX - YEAR_MIN);
    if (t < 0) t = 0;
    if (t > 1) t = 1;
    var hue = HUE_START + t * (HUE_END - HUE_START);
    return "hsl(" + hue + ", 100%, 50%)";
}}

function style(feature) {{
    var name = feature.properties.name;
    var year = experiences[name];
    var color = "#cccccc";
    if (year) {{
        color = yearToColor(year);
    }}
    return {{
        fillColor: color,
        weight: 1,
        opacity: 1,
        color: "white",
        fillOpacity: 0.75
    }};
}}

dbg("创建 colorLayer...");

var colorLayer = L.geoJSON(geojsonData, {{
    style: style,
    onEachFeature: function(feature, layer) {{
        var name = feature.properties.name || "未知";
        var year = experiences[name];
        var popup = "<b>" + name + "</b>";
        if (year) {{
            popup += "<br>经历年份: " + year;
        }} else {{
            popup += "<br>无经历数据";
        }}
        layer.bindPopup(popup);
    }}
}}).addTo(map);

dbg("colorLayer 完成");

var renderStart = Date.now();
var rendered = false;

function showTiming() {{
    if (rendered) return;
    rendered = true;
    var elapsed = ((Date.now() - renderStart) / 1000).toFixed(2);
    var panel = document.getElementById("timingPanel");
    panel.style.display = "block";
    panel.innerHTML = "✅ 渲染完成<br>耗时: " + elapsed + "s<br>要素: " + geojsonData.features.length;
    dbg("渲染完成 " + elapsed + "s");
}}

map.whenReady(function() {{
    dbg("whenReady");
    setTimeout(showTiming, 500);
}});

setTimeout(showTiming, 2000);

dbg("脚本完毕");
</script>

</body>
</html>
"""

# ========== 10. 导出 HTML 供排查 ==========
export_path = r"C:\Users\zhangweibo\Documents\ChinaAdminDivisonSHP\new\ribbon3_debug.html"
try:
    with open(export_path, "w", encoding="utf-8") as f:
        f.write(html)
    st.write(f"✅ 调试 HTML 已导出: `ribbon3_debug.html`")
except:
    pass

# ========== 11. 渲染 ==========
st.write("### 🗺️ 地图渲染中...")
st.components.v1.html(html, height=1200)