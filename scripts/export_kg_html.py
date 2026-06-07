#!/usr/bin/env python3
"""
Exporta el Knowledge Graph de Cognia a un archivo HTML interactivo con D3.js.

Uso:
    python scripts/export_kg_html.py [--output kg_export.html] [--limit 500]
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def build_graph_data(triples: list, limit: int) -> dict:
    """
    triples: lista de (subject, predicate, object, weight)
    Retorna {"nodes": [...], "links": [...]}
    Nodes: [{"id": str, "group": int}]  — group por grado de conexion
    Links: [{"source": str, "target": str, "value": float, "label": str}]
    """
    # Apply limit
    triples = triples[:limit]

    if not triples:
        return {"nodes": [], "links": []}

    # Count degree for each node
    degree: Counter = Counter()
    for subj, pred, obj, weight in triples:
        degree[subj] += 1
        degree[obj] += 1

    # Assign group based on degree quartile (1–4)
    all_degrees = sorted(degree.values())
    n = len(all_degrees)
    q1 = all_degrees[n // 4] if n >= 4 else 1
    q2 = all_degrees[n // 2] if n >= 2 else 1
    q3 = all_degrees[3 * n // 4] if n >= 4 else 1

    def _group(d: int) -> int:
        if d <= q1:
            return 1
        if d <= q2:
            return 2
        if d <= q3:
            return 3
        return 4

    # Build unique node list preserving insertion order
    seen_nodes: set = set()
    nodes = []
    for subj, pred, obj, weight in triples:
        for entity in (subj, obj):
            if entity not in seen_nodes:
                seen_nodes.add(entity)
                nodes.append({"id": entity, "group": _group(degree[entity])})

    links = [
        {"source": subj, "target": obj, "value": float(weight), "label": pred}
        for subj, pred, obj, weight in triples
    ]

    return {"nodes": nodes, "links": links}


def generate_html(graph_data: dict, triple_count: int) -> str:
    """
    Retorna HTML completo como string.
    - D3.js v7 desde CDN
    - SVG 100% width/height con zoom/pan
    - Nodos: circulos, color por grado, label al hover
    - Links: lineas con grosor proporcional al weight
    - Tooltip: subject -> predicate -> object
    - Stats panel: N nodos, N links
    - Estilo oscuro consistente con el dashboard
    """
    graph_json = json.dumps(graph_data, ensure_ascii=False)
    node_count = len(graph_data["nodes"])
    link_count = len(graph_data["links"])

    return f"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Cognia Knowledge Graph</title>
  <script src="https://d3js.org/d3.v7.min.js"></script>
  <style>
    * {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      background: #0f1117;
      color: #e2e8f0;
      font-family: 'Segoe UI', system-ui, sans-serif;
      height: 100vh;
      overflow: hidden;
      display: flex;
      flex-direction: column;
    }}
    header {{
      padding: 10px 18px;
      background: #1a1d27;
      border-bottom: 1px solid #2d3148;
      display: flex;
      align-items: center;
      gap: 16px;
      flex-shrink: 0;
    }}
    header h1 {{ font-size: 16px; font-weight: 600; color: #a78bfa; letter-spacing: .5px; }}
    .stats {{
      font-size: 12px;
      color: #94a3b8;
      margin-left: auto;
      display: flex;
      gap: 14px;
    }}
    .stat-badge {{
      background: #23263a;
      border: 1px solid #3b3f5e;
      border-radius: 5px;
      padding: 3px 9px;
    }}
    #graph-container {{ flex: 1; position: relative; overflow: hidden; }}
    svg {{ width: 100%; height: 100%; display: block; }}
    .link {{
      stroke: #4a5180;
      stroke-opacity: 0.55;
    }}
    .node circle {{
      stroke: #0f1117;
      stroke-width: 1.5px;
      cursor: pointer;
      transition: opacity .15s;
    }}
    .node circle:hover {{ opacity: 0.8; }}
    .node text {{
      font-size: 10px;
      fill: #cbd5e1;
      pointer-events: none;
      user-select: none;
    }}
    #tooltip {{
      position: absolute;
      background: #1e2135;
      border: 1px solid #4a5180;
      border-radius: 7px;
      padding: 8px 12px;
      font-size: 12px;
      color: #e2e8f0;
      pointer-events: none;
      opacity: 0;
      transition: opacity .15s;
      max-width: 280px;
      word-break: break-word;
      z-index: 10;
    }}
    #tooltip .pred {{ color: #818cf8; font-weight: 600; margin: 2px 0; }}
    #tooltip .weight {{ color: #64748b; font-size: 11px; }}
    #controls {{
      position: absolute;
      bottom: 14px;
      right: 14px;
      display: flex;
      flex-direction: column;
      gap: 6px;
    }}
    .ctrl-btn {{
      background: #23263a;
      border: 1px solid #3b3f5e;
      color: #94a3b8;
      border-radius: 5px;
      width: 30px;
      height: 30px;
      font-size: 16px;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
    }}
    .ctrl-btn:hover {{ background: #2d3148; color: #e2e8f0; }}
    #no-data {{
      position: absolute;
      top: 50%;
      left: 50%;
      transform: translate(-50%, -50%);
      color: #4a5180;
      font-size: 15px;
    }}
  </style>
</head>
<body>
  <header>
    <h1>Cognia Knowledge Graph</h1>
    <div class="stats">
      <span class="stat-badge">Nodos: <strong>{node_count}</strong></span>
      <span class="stat-badge">Links: <strong>{link_count}</strong></span>
      <span class="stat-badge">Triples totales: <strong>{triple_count}</strong></span>
    </div>
  </header>
  <div id="graph-container">
    <svg id="graph"></svg>
    <div id="tooltip"></div>
    <div id="controls">
      <button class="ctrl-btn" id="zoom-in" title="Zoom in">+</button>
      <button class="ctrl-btn" id="zoom-out" title="Zoom out">-</button>
      <button class="ctrl-btn" id="zoom-reset" title="Reset zoom" style="font-size:12px;">&#8635;</button>
    </div>
    {'<div id="no-data">El grafo no tiene datos todavia.</div>' if node_count == 0 else ''}
  </div>
  <script>
    const graphData = {graph_json};

    if (!graphData.nodes.length) {{
      document.getElementById('graph').style.display = 'none';
    }} else {{
      const container = document.getElementById('graph-container');
      const svg = d3.select('#graph');
      const g = svg.append('g');

      const color = d3.scaleOrdinal()
        .domain([1, 2, 3, 4])
        .range(['#6366f1', '#818cf8', '#a78bfa', '#c084fc']);

      // Zoom behaviour
      const zoom = d3.zoom()
        .scaleExtent([0.1, 8])
        .on('zoom', (event) => g.attr('transform', event.transform));
      svg.call(zoom);

      // Force simulation
      const sim = d3.forceSimulation(graphData.nodes)
        .force('link', d3.forceLink(graphData.links)
          .id(d => d.id)
          .distance(90)
          .strength(0.6))
        .force('charge', d3.forceManyBody().strength(-220))
        .force('center', d3.forceCenter(
          container.clientWidth / 2,
          container.clientHeight / 2))
        .force('collision', d3.forceCollide(18));

      // Links
      const link = g.append('g').selectAll('line')
        .data(graphData.links)
        .enter().append('line')
        .attr('class', 'link')
        .attr('stroke-width', d => Math.max(1, Math.min(4, d.value)));

      // Nodes
      const node = g.append('g').selectAll('.node')
        .data(graphData.nodes)
        .enter().append('g')
        .attr('class', 'node')
        .call(d3.drag()
          .on('start', (event, d) => {{
            if (!event.active) sim.alphaTarget(0.3).restart();
            d.fx = d.x; d.fy = d.y;
          }})
          .on('drag', (event, d) => {{ d.fx = event.x; d.fy = event.y; }})
          .on('end', (event, d) => {{
            if (!event.active) sim.alphaTarget(0);
            d.fx = null; d.fy = null;
          }}));

      node.append('circle')
        .attr('r', d => 5 + d.group * 2)
        .attr('fill', d => color(d.group));

      node.append('text')
        .attr('dy', d => 7 + d.group * 2)
        .attr('text-anchor', 'middle')
        .text(d => d.id.length > 18 ? d.id.slice(0, 17) + '...' : d.id);

      // Tooltip on link hover
      const tooltip = document.getElementById('tooltip');
      link
        .on('mouseover', (event, d) => {{
          tooltip.innerHTML = `
            <div><strong>${{d.source.id || d.source}}</strong></div>
            <div class="pred">&rarr; ${{d.label}}</div>
            <div><strong>${{d.target.id || d.target}}</strong></div>
            <div class="weight">peso: ${{d.value.toFixed(3)}}</div>
          `;
          tooltip.style.opacity = 1;
        }})
        .on('mousemove', (event) => {{
          tooltip.style.left = (event.offsetX + 14) + 'px';
          tooltip.style.top = (event.offsetY - 14) + 'px';
        }})
        .on('mouseout', () => {{ tooltip.style.opacity = 0; }});

      // Tooltip on node hover
      node
        .on('mouseover', (event, d) => {{
          tooltip.innerHTML = `<div><strong>${{d.id}}</strong></div><div class="weight">grado: ${{d.group}}</div>`;
          tooltip.style.opacity = 1;
        }})
        .on('mousemove', (event) => {{
          tooltip.style.left = (event.offsetX + 14) + 'px';
          tooltip.style.top = (event.offsetY - 14) + 'px';
        }})
        .on('mouseout', () => {{ tooltip.style.opacity = 0; }});

      sim.on('tick', () => {{
        link
          .attr('x1', d => d.source.x)
          .attr('y1', d => d.source.y)
          .attr('x2', d => d.target.x)
          .attr('y2', d => d.target.y);
        node.attr('transform', d => `translate(${{d.x}},${{d.y}})`);
      }});

      // Control buttons
      document.getElementById('zoom-in').addEventListener('click', () =>
        svg.transition().call(zoom.scaleBy, 1.4));
      document.getElementById('zoom-out').addEventListener('click', () =>
        svg.transition().call(zoom.scaleBy, 0.7));
      document.getElementById('zoom-reset').addEventListener('click', () =>
        svg.transition().call(zoom.transform, d3.zoomIdentity));
    }}
  </script>
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(
        description="Exporta el Knowledge Graph de Cognia a HTML interactivo con D3.js."
    )
    parser.add_argument("--output", default="kg_export.html",
                        help="Archivo de salida (default: kg_export.html)")
    parser.add_argument("--limit", type=int, default=500,
                        help="Maximo de triples a incluir (default: 500)")
    args = parser.parse_args()

    # Agrega raiz del proyecto al path para permitir imports de cognia.*
    sys.path.insert(0, str(Path(__file__).parent.parent))

    from cognia.knowledge.graph import KnowledgeGraph

    kg = KnowledgeGraph()
    triples = kg.get_all_triples(limit=args.limit)
    triple_count = len(triples)

    graph_data = build_graph_data(triples, limit=args.limit)
    html = generate_html(graph_data, triple_count)

    out = Path(args.output)
    out.write_text(html, encoding="utf-8")

    node_count = len(graph_data["nodes"])
    link_count = len(graph_data["links"])
    print(f"Exportado: {out.resolve()}")
    print(f"  Nodos: {node_count}  Links: {link_count}  Triples: {triple_count}")


if __name__ == "__main__":
    main()
