#!/usr/bin/env python3
"""
TASK_BOARD HTML Generator

Generates docs/TASK_BOARD.html from docs/TASK_BOARD.md for visual preview.

Supports new format: LANE + EPIC structure with 4-column tables (ID, Task, Tag, Status).

Usage:
    python3 scripts/generate_task_board_html.py

The HTML file is generated automatically and should NOT be edited manually.
Any changes should be made to docs/TASK_BOARD.md only.
"""

import re
from datetime import datetime
from pathlib import Path


# Statuses excluded from HTML output (completed/cancelled tasks)
EXCLUDED_STATUSES = {'DONE', 'CANCELLED'}
# Statuses shown in HTML
ACTIVE_STATUSES = {'TODO', 'IN_PROGRESS', 'READY', 'FROZEN', 'BACKLOG'}


def get_status_badge(status: str) -> str:
    """Generate color-coded HTML badge for task status."""
    status_colors = {
        'TODO': '#ffc107',          # Yellow
        'IN_PROGRESS': '#9c27b0',   # Purple
        'READY': '#2196f3',         # Blue
        'TESTED': '#ff9800',        # Orange
        'DONE': '#4caf50',          # Green
        'BLOCKED': '#f44336',       # Red
        'FROZEN': '#607d8b',        # Blue-grey
        'CANCELLED': '#9e9e9e',     # Grey
        'BACKLOG': '#795548',       # Brown
    }
    return f'<span class="status-badge status-{status.upper()}">{status}</span>'


def parse_markdown_tasks(markdown_content: str) -> dict:
    """Parse the Markdown file and extract all data."""
    data = {
        'title': 'TASK_BOARD',
        'statuses': [],
        'lanes': [],
        'epics': [],
        'priority': None,
        'rules': [],
        'workflow': '',
        'update_date': ''
    }
    
    lines = markdown_content.split('\n')
    
    # Parse title
    if lines and lines[0].startswith('# '):
        data['title'] = lines[0][2:].strip()
    
    # Parse status table
    in_status_section = False
    status_lines = []
    for i, line in enumerate(lines):
        if '## Статусы задач' in line:
            in_status_section = True
            continue
        if in_status_section:
            if line.startswith('|') and '---' not in line:
                status_lines.append(line)
            elif line.startswith('##'):
                in_status_section = False
    
    for line in status_lines:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 2:
            data['statuses'].append({'name': cells[0], 'desc': cells[1]})
    
    # Parse priority section (as info block, no internal parsing)
    in_priority = False
    priority_lines = []
    for line in lines:
        if '## Текущий приоритет' in line:
            in_priority = True
            continue
        if in_priority:
            if line.startswith('##'):
                in_priority = False
            elif line.strip():
                priority_lines.append(line.strip())
    if priority_lines:
        data['priority'] = '\n'.join(priority_lines)
    
    # Parse LANE and EPIC sections
    current_section = None  # 'lane', 'epic', or None
    current_title = None
    table_rows = []
    section_type = None  # 'lane' or 'epic'
    
    i = 0
    while i < len(lines):
        line = lines[i]
        
        # LANE section
        lane_match = re.match(r'##\s+LANE:\s+([A-Z]+)\s+[-—]\s+(.+)', line)
        if lane_match:
            # Save previous section
            if current_title and table_rows:
                if section_type == 'lane':
                    data['lanes'].append({'title': current_title, 'status': extract_section_status(table_rows)})
                elif section_type == 'epic':
                    tasks = parse_tasks_table(table_rows, filter_status=True)
                    data['epics'].append({'title': current_title, 'tasks': tasks})
            
            current_title = f"{lane_match.group(1)} — {lane_match.group(2)}"
            section_type = 'lane'
            table_rows = []
            current_section = 'lane'
            
            # Collect description lines until --- or next ##
            desc_lines = []
            i += 1
            while i < len(lines):
                next_line = lines[i]
                if next_line.startswith('---') or (next_line.startswith('##') and next_line.strip()):
                    break
                desc_lines.append(next_line.strip())
                i += 1
            
            # Store description in table_rows temporarily (for status extraction)
            if desc_lines:
                table_rows = desc_lines
            
            # Extract status from description
            status = 'ACTIVE'
            for desc in desc_lines:
                if desc.startswith('**Статус:**'):
                    if 'FROZEN' in desc:
                        status = 'FROZEN'
                    break
            
            # Save LANE immediately (no task table expected)
            data['lanes'].append({'title': current_title, 'status': status})
            current_title = None
            table_rows = []
            current_section = None
            section_type = None
            continue
        
        # EPIC section
        epic_match = re.match(r'##\s+EPIC:\s+([A-Z]+)\s+[-—]\s+(.+)', line)
        if epic_match:
            # Save previous section
            if current_title and table_rows:
                if section_type == 'epic':
                    tasks = parse_tasks_table(table_rows, filter_status=True)
                    data['epics'].append({'title': current_title, 'tasks': tasks})
            
            current_title = f"{epic_match.group(1)} — {epic_match.group(2)}"
            section_type = 'epic'
            table_rows = []
            current_section = 'epic'
            i += 1
            continue
        
        # Table row within current EPIC section (LANE has no task table)
        if line.startswith('|') and current_section == 'epic':
            if '---' not in line:
                table_rows.append(line)
        
        # End of EPIC section (--- or ##)
        elif line.startswith('---') or (line.startswith('## EPIC') and current_section == 'epic'):
            if current_title and table_rows:
                tasks = parse_tasks_table(table_rows, filter_status=True)
                data['epics'].append({'title': current_title, 'tasks': tasks})
                current_title = None
                table_rows = []
                current_section = None
                section_type = None
        
        i += 1
    
    # Don't forget last EPIC
    if current_title and table_rows:
        tasks = parse_tasks_table(table_rows, filter_status=True)
        data['epics'].append({'title': current_title, 'tasks': tasks})
    
    # Parse rules
    in_rules = False
    for line in lines:
        if '## Правила управления задачами' in line:
            in_rules = True
            continue
        if in_rules:
            rule_match = re.match(r'^\d+\.\s+(.+)$', line.strip())
            if rule_match:
                data['rules'].append(rule_match.group(1))
            elif line.startswith('##'):
                in_rules = False
    
    # Parse workflow
    for i, line in enumerate(lines):
        if '## Workflow' in line and i + 1 < len(lines):
            for j in range(i+1, min(i+5, len(lines))):
                if lines[j].strip().startswith('```'):
                    for k in range(j+1, min(j+3, len(lines))):
                        if '```' in lines[k]:
                            data['workflow'] = lines[k-1].strip()
                            break
                    break
    
    # Find update date
    for line in lines:
        match = re.search(r'\*Обновлено:\s*(\d{4}-\d{2}-\d{2})\*', line)
        if match:
            data['update_date'] = match.group(1)
            break
    
    if not data['update_date']:
        data['update_date'] = datetime.now().strftime('%Y-%m-%d')
    
    return data


def extract_section_status(table_lines: list) -> str:
    """Extract status from LANE description (last line before table)."""
    return 'ACTIVE'


def parse_tasks_table(table_lines: list, filter_status: bool = False) -> list:
    """Parse task rows from Markdown table with 4 columns (ID, Task, Tag, Status)."""
    tasks = []
    for line in table_lines:
        cells = [c.strip() for c in line.split('|')[1:-1]]
        if len(cells) >= 4:
            task_id = cells[0]
            # Skip header row
            if task_id == 'ID':
                continue
            task_name = cells[1]
            tag = cells[2] if len(cells) > 2 else ''
            status = cells[3].replace('**', '').strip() if len(cells) > 3 else ''
            
            # Filter by status if requested
            if filter_status and status.upper() in EXCLUDED_STATUSES:
                continue
            
            tasks.append({
                'id': task_id,
                'name': task_name,
                'tag': tag,
                'status': status
            })
        elif len(cells) >= 3:
            # Fallback: 3 columns (ID, Task, Status) — treat as old format
            task_id = cells[0]
            if task_id == 'ID':
                continue
            task_name = cells[1]
            status = cells[2].replace('**', '').strip()
            
            if filter_status and status.upper() in EXCLUDED_STATUSES:
                continue
            
            tasks.append({
                'id': task_id,
                'name': task_name,
                'tag': '',
                'status': status
            })
    return tasks


def generate_html(data: dict) -> str:
    """Generate complete HTML document from parsed data."""
    
    html = f'''<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{data['title']}</title>
    <style>
        * {{
            box-sizing: border-box;
        }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
            line-height: 1.6;
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
            background: #f5f5f5;
            color: #333;
        }}
        h1 {{
            color: #1a1a2e;
            border-bottom: 3px solid #4caf50;
            padding-bottom: 10px;
        }}
        h2 {{
            color: #16213e;
            margin-top: 30px;
            border-left: 4px solid #4caf50;
            padding-left: 10px;
        }}
        h3 {{
            color: #333;
            margin-top: 20px;
        }}
        .priority {{
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            padding: 15px 20px;
            border-radius: 8px;
            margin: 20px 0;
            font-size: 1.1em;
            white-space: pre-line;
        }}
        .priority strong {{
            font-size: 1.2em;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            margin: 15px 0;
            background: white;
            border-radius: 8px;
            overflow: hidden;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        th {{
            background: #1a1a2e;
            color: white;
            padding: 12px;
            text-align: left;
            font-weight: 600;
        }}
        td {{
            padding: 12px;
            border-bottom: 1px solid #eee;
        }}
        tr:hover {{
            background: #f8f9fa;
        }}
        .status-badge {{
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.85em;
            font-weight: 600;
            color: white;
            text-transform: uppercase;
        }}
        .status-TODO {{ background: #ffc107; color: #333; }}
        .status-READY {{ background: #2196f3; }}
        .status-IN_PROGRESS {{ background: #9c27b0; }}
        .status-TESTED {{ background: #ff9800; }}
        .status-DONE {{ background: #4caf50; }}
        .status-BLOCKED {{ background: #f44336; }}
        .status-FROZEN {{ background: #607d8b; }}
        .status-CANCELLED {{ background: #9e9e9e; }}
        .status-BACKLOG {{ background: #795548; }}
        
        .status-table {{
            background: white;
        }}
        .status-table th {{
            background: #333;
        }}
        
        .rules {{
            background: #fff3cd;
            padding: 15px;
            border-radius: 8px;
            margin: 20px 0;
            border-left: 4px solid #ffc107;
        }}
        .rules p {{
            margin: 8px 0;
        }}
        .workflow {{
            background: #e3f2fd;
            padding: 15px;
            border-radius: 8px;
            font-family: monospace;
            font-size: 1.1em;
            text-align: center;
        }}
        .footer {{
            margin-top: 30px;
            padding-top: 20px;
            border-top: 1px solid #ddd;
            color: #666;
            font-size: 0.9em;
            text-align: center;
        }}
        .generated {{
            color: #999;
            font-style: italic;
        }}
        .epic-card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
        }}
        .lane-card {{
            background: white;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 8px rgba(0,0,0,0.1);
            border-left: 4px solid #4caf50;
        }}
        .lane-card.frozen {{
            border-left-color: #607d8b;
            opacity: 0.7;
        }}
        .task-id {{
            font-weight: 600;
            color: #666;
            font-family: monospace;
        }}
        .task-tag {{
            font-size: 0.85em;
            color: #888;
        }}
        .empty-message {{
            color: #888;
            font-style: italic;
            padding: 20px;
            text-align: center;
        }}
        .section-label {{
            display: inline-block;
            padding: 2px 8px;
            border-radius: 4px;
            font-size: 0.75em;
            font-weight: 600;
            text-transform: uppercase;
            margin-right: 8px;
        }}
        .label-lane {{ background: #667eea; color: white; }}
        .label-epic {{ background: #4caf50; color: white; }}
    </style>
</head>
<body>
    <h1>📋 {data['title']}</h1>
    
    <p><em>Единственный source of truth для статусов и списка задач проекта.</em></p>
'''
    
    # Status legend
    if data['statuses']:
        html += '''
    <h2>📌 Статусы задач</h2>
    <table class="status-table">
        <thead>
            <tr>
                <th>Статус</th>
                <th>Описание</th>
            </tr>
        </thead>
        <tbody>
'''
        for s in data['statuses']:
            html += f'''            <tr>
                <td>{get_status_badge(s['name'])}</td>
                <td>{s['desc']}</td>
            </tr>
'''
        html += '''        </tbody>
    </table>
'''
    
    # Priority
    if data['priority']:
        html += f'''
    <h2>🎯 Текущий приоритет</h2>
    <div class="priority">
        {data['priority']}
    </div>
'''
    
    # LANE sections
    for lane in data['lanes']:
        is_frozen = 'FROZEN' in lane.get('status', '').upper()
        html += f'''
    <div class="lane-card{' frozen' if is_frozen else ''}">
        <h2><span class="section-label label-lane">LANE</span>{lane['title']}</h2>
        <p class="empty-message">Информационный блок. Задачи — в соответствующих EPIC.</p>
    </div>
'''
    
    # EPICs
    for epic in data['epics']:
        epic_title = epic['title']
        html += f'''
    <div class="epic-card">
        <h2><span class="section-label label-epic">EPIC</span>{epic_title}</h2>
'''
        if epic['tasks']:
            html += '''        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Задача</th>
                    <th>Тег</th>
                    <th>Статус</th>
                </tr>
            </thead>
            <tbody>
'''
            for task in epic['tasks']:
                tag_html = f'<span class="task-tag">{task["tag"]}</span>' if task.get('tag') else ''
                html += f'''                <tr>
                    <td class="task-id">{task['id']}</td>
                    <td>{task['name']}</td>
                    <td>{tag_html}</td>
                    <td>{get_status_badge(task['status'])}</td>
                </tr>
'''
            html += '''            </tbody>
        </table>
'''
        else:
            html += '''        <p class="empty-message">Все задачи выполнены</p>
'''
        html += '''
    </div>
'''
    
    # Rules
    if data['rules']:
        html += '''
    <h2>📜 Правила управления задачами</h2>
    <div class="rules">
'''
        for rule in data['rules']:
            html += f'        <p>{rule}</p>\n'
        html += '''    </div>
'''
    
    # Workflow
    if data['workflow']:
        html += f'''
    <h2>🔄 Workflow</h2>
    <div class="workflow">
        {data['workflow']}
    </div>
'''
    
    # Footer
    html += f'''
    <div class="footer">
        <p>Обновлено: {data['update_date']}</p>
        <p class="generated">HTML сгенерирован автоматически из docs/TASK_BOARD.md</p>
    </div>
</body>
</html>
'''
    
    return html


def main():
    """Main function to generate HTML from Markdown."""
    md_path = Path('docs/TASK_BOARD.md')
    html_path = Path('docs/TASK_BOARD.html')
    
    if not md_path.exists():
        print(f'Error: {md_path} not found')
        return 1
    
    # Read Markdown content
    markdown_content = md_path.read_text(encoding='utf-8')
    
    # Parse and generate HTML
    data = parse_markdown_tasks(markdown_content)
    html_content = generate_html(data)
    
    # Write HTML file
    html_path.write_text(html_content, encoding='utf-8')
    
    print(f'Generated {html_path}')
    print(f'Open {html_path} in a browser to view the task board')
    
    # Print summary
    total_tasks = sum(len(epic['tasks']) for epic in data['epics'])
    print(f'Total LANEs: {len(data["lanes"])}, Total EPICs: {len(data["epics"])}, Total tasks in HTML: {total_tasks}')
    
    return 0


if __name__ == '__main__':
    exit(main())
