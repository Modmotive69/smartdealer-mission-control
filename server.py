from flask import Flask, send_from_directory, request, jsonify, Response, send_file
import json, os, subprocess, yaml
from datetime import datetime

app = Flask(__name__, static_folder='.')

# Paths
BASE_DIR = '/Users/scottanderson/.openclaw/workspace'
MC_DIR = '/Users/scottanderson/.openclaw/workspace/mission_control'
TASKS_FILE = f'{MC_DIR}/tasks.json'
DIST_LISTS_FILE = f'{BASE_DIR}/distribution_lists.json'
TOKEN_STATS_FILE  = f'{MC_DIR}/token_stats.json'
CALENDAR_FILE     = f'{MC_DIR}/calendar.json'
HUBSPOT_CONFIG = f'{BASE_DIR}/hubspot.config.yml'

# ─── Helpers ────────────────────────────────────────────────────────────────

def load_json_file(path):
    if not os.path.exists(path):
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except:
        return {}

def save_json_file(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def load_hubspot_config():
    if not os.path.exists(HUBSPOT_CONFIG):
        return None
    with open(HUBSPOT_CONFIG) as f:
        return yaml.safe_load(f)

# ─── Static files ───────────────────────────────────────────────────────────

@app.route('/')
def index():
    return send_from_directory('.', 'index.html')

@app.route('/<path:path>')
def static_files(path):
    return send_from_directory('.', path)

# ─── Tasks ──────────────────────────────────────────────────────────────────

@app.route('/api/tasks', methods=['GET'])
def get_tasks():
    return jsonify(load_json_file(TASKS_FILE))

@app.route('/api/tasks', methods=['POST'])
def add_task():
    data = request.json or {}
    tasks = load_json_file(TASKS_FILE)
    new_task = {
        "id": str(data.get('id', datetime.now().timestamp())),
        "desc": data.get('desc', ''),
        "status": data.get('status', 'todo'),
        "created": data.get('created', datetime.now().isoformat())
    }
    tasks.setdefault('tasks', []).append(new_task)
    save_json_file(TASKS_FILE, tasks)
    return jsonify({"status": "success", "task": new_task})

@app.route('/api/tasks/<task_id>', methods=['PUT'])
def update_task(task_id):
    data = request.json or {}
    tasks = load_json_file(TASKS_FILE)
    for task in tasks.get('tasks', []):
        if task['id'] == task_id:
            task['status'] = data.get('status', task['status'])
            save_json_file(TASKS_FILE, tasks)
            return jsonify({"status": "success", "task": task})
    return jsonify({"status": "error", "message": "Task not found"}), 404

@app.route('/api/tasks/<task_id>', methods=['DELETE'])
def delete_task(task_id):
    tasks = load_json_file(TASKS_FILE)
    tasks['tasks'] = [t for t in tasks.get('tasks', []) if t['id'] != task_id]
    save_json_file(TASKS_FILE, tasks)
    return jsonify({"status": "success"})

# ─── Files (Apollo leads) ────────────────────────────────────────────────────

@app.route('/api/files', methods=['GET'])
def get_files():
    LEADS_DIR = f'{BASE_DIR}/research/leads'
    apollo_files, scraped_files = [], []
    if os.path.exists(LEADS_DIR):
        for f in os.listdir(LEADS_DIR):
            if not f.endswith('.csv'):
                continue
            path = os.path.join(LEADS_DIR, f)
            size = os.path.getsize(path)
            try:
                records = sum(1 for line in open(path, encoding='utf-8', errors='ignore')) - 1
            except:
                records = 0
            file_data = {"name": f, "size": f"{size/1024:.1f} KB", "records": max(0, records)}
            fn = f.lower()
            if 'apollo' in fn and 'injected' not in fn:
                apollo_files.append(file_data)
            elif 'dark_matter' in fn:
                scraped_files.append(file_data)
    return jsonify({"apollo_files": apollo_files, "scraped_files": scraped_files})

# ─── Distribution Lists ──────────────────────────────────────────────────────

@app.route('/api/dist-lists', methods=['GET'])
def get_dist_lists():
    return jsonify(load_json_file(DIST_LISTS_FILE))

@app.route('/api/dist-lists', methods=['POST'])
def create_dist_list():
    data = request.json or {}
    all_lists = load_json_file(DIST_LISTS_FILE)
    new_list = {
        "id": str(datetime.now().timestamp()),
        "name": data.get('name', 'New List'),
        "description": data.get('description', ''),
        "contacts": []
    }
    all_lists.setdefault('lists', []).append(new_list)
    save_json_file(DIST_LISTS_FILE, all_lists)
    return jsonify({"status": "success", "list": new_list})

@app.route('/api/dist-lists/<list_id>/contacts', methods=['POST'])
def add_contact(list_id):
    data = request.json or {}
    all_lists = load_json_file(DIST_LISTS_FILE)
    for lst in all_lists.get('lists', []):
        if lst['id'] == list_id:
            lst.setdefault('contacts', []).append(data)
            save_json_file(DIST_LISTS_FILE, all_lists)
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "List not found"}), 404

@app.route('/api/dist-lists/<list_id>/contacts/<path:email>', methods=['DELETE'])
def remove_contact(list_id, email):
    all_lists = load_json_file(DIST_LISTS_FILE)
    for lst in all_lists.get('lists', []):
        if lst['id'] == list_id:
            lst['contacts'] = [c for c in lst.get('contacts', []) if c.get('email') != email]
            save_json_file(DIST_LISTS_FILE, all_lists)
            return jsonify({"status": "success"})
    return jsonify({"status": "error", "message": "List not found"}), 404

# ─── Pipeline (HubSpot deals) ────────────────────────────────────────────────

@app.route('/api/pipeline', methods=['GET'])
def get_pipeline():
    config = load_hubspot_config()
    if not config:
        return jsonify({"deals": [], "error": "HubSpot not configured"})
    try:
        import requests
        token = config['portals'][0]['auth']['tokenInfo']['accessToken']
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        resp = requests.get(
            "https://api.hubapi.com/crm/v3/objects/deals",
            headers=headers, params={"limit": 50, "properties": "dealname,amount,dealstage,closedate"}
        )
        if resp.ok:
            deals = [{"id": d['id'], "properties": d['properties']} for d in resp.json().get('results', [])]
            return jsonify({"deals": deals})
        return jsonify({"deals": [], "error": f"HTTP {resp.status_code}"})
    except Exception as e:
        return jsonify({"deals": [], "error": str(e)})

# ─── Inbox ──────────────────────────────────────────────────────────────────

@app.route('/api/inbox', methods=['GET'])
def get_inbox():
    return jsonify({"emails": [], "messages": []})

@app.route('/api/inbox/<email_id>/read', methods=['POST'])
def mark_read(email_id):
    return jsonify({"status": "success"})

# ─── Scout Archive ───────────────────────────────────────────────────────────

@app.route('/api/scout-archive', methods=['GET'])
def get_scout_archive():
    ARCHIVE_DIR = f'{BASE_DIR}/research/scout'
    emails = []
    if os.path.exists(ARCHIVE_DIR):
        for f in sorted(os.listdir(ARCHIVE_DIR), reverse=True)[:20]:
            if f.endswith('.json'):
                with open(os.path.join(ARCHIVE_DIR, f)) as fp:
                    try:
                        emails.append(json.load(fp))
                    except:
                        pass
    return jsonify({"emails": emails})

# ─── Revenue ────────────────────────────────────────────────────────────────

@app.route('/api/revenue', methods=['GET'])
def get_revenue():
    rev_file = f'{BASE_DIR}/research/revenue.json'
    return jsonify(load_json_file(rev_file))

@app.route('/api/revenue', methods=['POST'])
def add_revenue():
    data = request.json or {}
    rev_file = f'{BASE_DIR}/research/revenue.json'
    rev_data = load_json_file(rev_file)
    rev_data.setdefault('entries', []).append({
        "date": data.get('date', datetime.now().strftime('%Y-%m-%d')),
        "mrr": data.get('mrr', 0),
        "note": data.get('note', '')
    })
    save_json_file(rev_file, rev_data)
    return jsonify({"status": "success", "entry": rev_data['entries'][-1]})

# ─── Knowledge Base ──────────────────────────────────────────────────────────

@app.route('/api/kb', methods=['GET'])
def kb_list():
    KB_DIR = f'{BASE_DIR}/kb'
    files = []
    if os.path.exists(KB_DIR):
        for root, dirs, filenames in os.walk(KB_DIR):
            for f in filenames:
                if f.endswith(('.md', '.txt', '.json', '.yml', '.yaml')):
                    full = os.path.join(root, f)
                    files.append({
                        "name": f,
                        "path": full.replace(KB_DIR + '/', ''),
                        "size": os.path.getsize(full)
                    })
    return jsonify({"files": files})

@app.route('/api/kb/file', methods=['GET'])
def kb_file():
    path = request.args.get('path', '')
    KB_DIR = f'{BASE_DIR}/kb'
    safe_path = os.path.normpath(path).replace('..', '')
    full_path = os.path.join(KB_DIR, safe_path)
    if not full_path.startswith(KB_DIR):
        return jsonify({"error": "Invalid path"}), 400
    if not os.path.exists(full_path):
        return jsonify({"error": "File not found"}), 404
    try:
        with open(full_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read()
        return jsonify({"content": content, "path": path})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─── Models ─────────────────────────────────────────────────────────────────

OPENCLAW_CONFIG = '/Users/scottanderson/.openclaw/openclaw.json'

@app.route('/api/models', methods=['GET'])
def get_models():
    config = load_json_file(OPENCLAW_CONFIG)
    model_defaults = config.get('agents', {}).get('defaults', {}).get('model', {})
    primary = model_defaults.get('primary', 'minimax-portal/MiniMax-M2.7')
    fallbacks = model_defaults.get('fallbacks', [
        'anthropic/claude-sonnet-4-6',
        'google/gemini-2.5-flash',
        'google/gemini-2.5-pro',
        'anthropic/claude-opus-4-6',
        'ollama/llama3.2:3b'
    ])
    chain = [primary] + fallbacks

    model_meta = {
        'minimax-portal/MiniMax-M2.7':     {'name': 'MiniMax M2.7',        'provider': 'MiniMax',   'input_cost_per_m': 0.30,  'output_cost_per_m': 1.20,  'context_k': 200,  'role': 'primary'},
        'anthropic/claude-sonnet-4-6':      {'name': 'Claude Sonnet 4.6',   'provider': 'Anthropic', 'input_cost_per_m': 3.00,  'output_cost_per_m': 15.00, 'context_k': 200,  'role': 'fallback'},
        'google/gemini-2.5-flash':          {'name': 'Gemini 2.5 Flash',    'provider': 'Google',    'input_cost_per_m': 0.075, 'output_cost_per_m': 0.30,  'context_k': 1000, 'role': 'fallback'},
        'google/gemini-2.5-pro':            {'name': 'Gemini 2.5 Pro',      'provider': 'Google',    'input_cost_per_m': 1.25,  'output_cost_per_m': 10.00, 'context_k': 2000, 'role': 'fallback'},
        'anthropic/claude-opus-4-6':        {'name': 'Claude Opus 4.6',     'provider': 'Anthropic', 'input_cost_per_m': 15.00, 'output_cost_per_m': 75.00, 'context_k': 200,  'role': 'fallback'},
        'ollama/llama3.2:3b':               {'name': 'Ollama llama3.2:3b',  'provider': 'Ollama',    'input_cost_per_m': 0,     'output_cost_per_m': 0,     'context_k': 128,  'role': 'local'},
    }

    chain_details = []
    for i, model_id in enumerate(chain):
        meta = model_meta.get(model_id, {'name': model_id, 'provider': 'Unknown', 'input_cost_per_m': 0, 'output_cost_per_m': 0, 'context_k': 128, 'role': 'fallback'})
        chain_details.append({
            'id': model_id,
            'position': i,
            'is_primary': i == 0,
            **meta
        })

    return jsonify({
        'active_model': primary,
        'primary': primary,
        'fallbacks': fallbacks,
        'chain': chain_details,
        'updated_at': datetime.now().isoformat()
    })

# ─── Token Stats ────────────────────────────────────────────────────────────

@app.route('/api/token-stats', methods=['GET'])
def get_token_stats():
    return jsonify(load_json_file(TOKEN_STATS_FILE))

@app.route('/api/token-stats', methods=['POST'])
def post_token_stats():
    data = request.json or {}
    stats = load_json_file(TOKEN_STATS_FILE)
    stats['last_updated'] = datetime.now().isoformat()

    # Handle new full breakdown format from push_full_cost_breakdown.py
    if 'breakdown' in data:
        today = data.get('date', datetime.now().strftime('%Y-%m-%d'))
        # Store the full breakdown keyed by date
        stats.setdefault('daily_breakdowns', {})[today] = {
            'breakdown': data['breakdown'],
            'total_cost_usd': data.get('daily_cost_usd', 0),
            'total_turns': data.get('daily_turns', 0),
            'sessions_scanned': data.get('sessions_scanned', 0),
            'last_updated': datetime.now().isoformat()
        }
        # Also update flat totals for backward compat
        stats['cost_usd'] = data.get('daily_cost_usd', 0)
        stats['tokens_in'] = data.get('tokens_in', 0)
        stats['tokens_out'] = data.get('tokens_out', 0)
        stats['cache_hit_tokens'] = data.get('cache_hit_tokens', 0)
        stats['model'] = data.get('model', 'multi-model')
        stats['date'] = today
        stats['time'] = data.get('time', '')
        save_json_file(TOKEN_STATS_FILE, stats)
        return jsonify({'status': 'success'})

    # Legacy single-session push — still supported
    stats.setdefault('sessions', []).append(data)
    totals = {}
    for s in stats.get('sessions', []):
        model = s.get('model', 'unknown')
        if model not in totals:
            totals[model] = {'tokens_in': 0, 'tokens_out': 0, 'cache_hit_tokens': 0, 'total_cost_usd': 0, 'session_count': 0}
        t = totals[model]
        t['tokens_in'] += s.get('tokens_in', 0)
        t['tokens_out'] += s.get('tokens_out', 0)
        t['cache_hit_tokens'] += s.get('cache_hit_tokens', 0)
        t['total_cost_usd'] += s.get('cost_usd', 0)
        t['session_count'] += 1
    stats['totals'] = totals
    stats['cost_usd'] = sum(t['total_cost_usd'] for t in totals.values())
    stats['tokens_in'] = sum(t['tokens_in'] for t in totals.values())
    stats['tokens_out'] = sum(t['tokens_out'] for t in totals.values())
    stats['cache_hit_tokens'] = sum(t['cache_hit_tokens'] for t in totals.values())
    save_json_file(TOKEN_STATS_FILE, stats)
    return jsonify({'status': 'success'})

# ─── Calendar CRUD ───────────────────────────────────────────────

@app.route('/api/calendar', methods=['GET'])
def get_calendar():
    cal = load_json_file(CALENDAR_FILE)
    events = cal.get('events', [])
    # Pull tasks with dates for calendar overlay
    tasks_data = load_json_file(TASKS_FILE)
    tasks = [t for t in tasks_data.get('tasks', []) if t.get('date')]
    # Pull memory dates
    mem_dir = f'{BASE_DIR}/memory'
    memory_dates = []
    if os.path.exists(mem_dir):
        for f in os.listdir(mem_dir):
            if f.endswith('.md') and len(f) == 13:  # YYYY-MM-DD.md
                memory_dates.append(f.replace('.md', ''))
    # Pull active crons from OpenClaw
    crons = []
    try:
        cron_result = subprocess.run(
            ['node', '-e', "const f=require('/opt/homebrew/lib/node_modules/openclaw/src/index.js');f.listCrons().then(r=>console.log(JSON.stringify(r))).catch(()=>console.log('[]'))"],
            capture_output=True, text=True, timeout=5
        )
        raw = cron_result.stdout.strip()
        if raw:
            crons = json.loads(raw) if raw.startswith('[') else []
    except Exception:
        crons = []
    return jsonify({'events': events, 'tasks': tasks, 'memoryDates': memory_dates, 'crons': crons})

@app.route('/api/calendar', methods=['POST'])
def add_calendar_event():
    data = request.json or {}
    cal = load_json_file(CALENDAR_FILE)
    cal.setdefault('events', [])
    data['id'] = data.get('id') or f'ev-{datetime.now().strftime("%Y%m%d%H%M%S")}'
    data['created'] = datetime.now().isoformat()
    cal['events'].append(data)
    save_json_file(CALENDAR_FILE, cal)
    return jsonify({'status': 'success', 'id': data['id']})

@app.route('/api/calendar/<event_id>', methods=['DELETE'])
def delete_calendar_event(event_id):
    cal = load_json_file(CALENDAR_FILE)
    cal['events'] = [e for e in cal.get('events', []) if e.get('id') != event_id]
    save_json_file(CALENDAR_FILE, cal)
    return jsonify({'status': 'success'})

# ─── Calendar / Events (SSE) ───────────────────────────────────────────────

@app.route('/api/events')
def events():
    def generate():
        import time
        while True:
            try:
                result = subprocess.run(['launchctl', 'list'], capture_output=True, text=True)
                cron_jobs = []
                for line in result.stdout.split('\n'):
                    if 'ai.penpen' in line or 'com.openclaw' in line:
                        parts = line.split()
                        if len(parts) >= 3:
                            cron_jobs.append({
                                "name": ' '.join(parts[2:]),
                                "pid": parts[0],
                                "status": parts[1]
                            })
                data = json.dumps({"cron_jobs": cron_jobs, "time": datetime.now().isoformat()})
                yield f"data: {data}\n\n"
            except Exception as e:
                yield f"data: {{'error': str(e)}}\n\n"
            time.sleep(30)
    return Response(generate(), mimetype='text/event-stream')

# ─── Apollo Pull ────────────────────────────────────────────────────────────

@app.route('/api/apollo/pull', methods=['POST'])
def apollo_pull():
    try:
        result = subprocess.run(
            ['python3', f'{BASE_DIR}/scripts/apollo_pull.py'],
            capture_output=True, text=True, timeout=120
        )
        return jsonify({"status": "success", "output": result.stdout[-500:]})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ─── HubSpot Contacts ───────────────────────────────────────────────────────

@app.route('/api/hubspot/contacts', methods=['GET'])
def hubspot_contacts():
    config = load_hubspot_config()
    if not config:
        return jsonify({"contacts": [], "error": "HubSpot not configured"})
    try:
        import requests
        token = config['portals'][0]['auth']['tokenInfo']['accessToken']
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        resp = requests.get(
            "https://api.hubapi.com/crm/v3/objects/contacts",
            headers=headers, params={"limit": 20, "properties": "email,firstname,lastname,jobtitle,company,phone"}
        )
        if resp.ok:
            contacts = [{"id": c['id'], "properties": c['properties']} for c in resp.json().get('results', [])]
            return jsonify({"contacts": contacts})
        return jsonify({"contacts": [], "error": f"HTTP {resp.status_code}"})
    except Exception as e:
        return jsonify({"contacts": [], "error": str(e)})

# ─── Newsletter Subscribe / Unsubscribe ───────────────────────────────────────

@app.route('/subscribe', methods=['GET'])
def subscribe_page():
    """Serve the subscribe landing page."""
    sub_path = os.path.join(os.path.dirname(__file__), 'subscribe.html')
    if os.path.exists(sub_path):
        return send_file(sub_path)
    return "Subscribe page not found. Place subscribe.html in mission_control/ directory.", 404

@app.route('/subscribe', methods=['POST'])
def subscribe_post():
    """Handle newsletter subscriptions → add to HubSpot."""
    try:
        data = request.json or {}
        email = (data.get('email') or '').strip().lower()
        name = (data.get('name') or '').strip()
        
        if not email or '@' not in email:
            return jsonify({'success': False, 'error': 'Valid email required'})
        
        config = load_hubspot_config()
        if not config:
            return jsonify({'success': False, 'error': 'HubSpot not configured'})
        
        import requests as _req
        token = config['portals'][0]['auth']['tokenInfo']['accessToken']
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        
        # Try to create contact — HubSpot returns 409 if email exists (upsert)
        create_url = "https://api.hubapi.com/crm/v3/objects/contacts"
        create_payload = {
            "properties": {
                "email": email,
                "firstname": name.split()[0] if name else ''
            }
        }
        create_resp = _req.post(create_url, headers=headers, json=create_payload)
        
        if create_resp.status_code == 201:
            action = 'created'
        elif create_resp.status_code == 409:
            # Contact already exists — they're subscribed
            action = 'already_subscribed'
        else:
            action = 'error_' + str(create_resp.status_code)
        
        return jsonify({'success': True, 'action': action, 'email': email, 'note': 'Added to Franchise Focus mailing list'})
    
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})

@app.route('/unsubscribe', methods=['GET'])
def unsubscribe_get():
    """Handle unsubscribes via query param ?email=xxx"""
    email = request.args.get('email', '').strip().lower()
    
    unsub_path = os.path.join(os.path.dirname(__file__), 'unsubscribe.html')
    
    config = load_hubspot_config()
    if config and email:
        try:
            import requests as _req
            token = config['portals'][0]['auth']['tokenInfo']['accessToken']
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            
            # Find contact
            search_url = "https://api.hubapi.com/crm/v3/objects/contacts/search"
            search_payload = {"filterGroups":[{"filters":[{"propertyName":"email","operator":"EQ","value":email}]}]}
            resp = _req.post(search_url, headers=headers, json=search_payload)
            
            if resp.ok and resp.json().get('results'):
                contact_id = resp.json()['results'][0]['id']
                # Mark as unsubscribed
                update_url = f"https://api.hubapi.com/crm/v3/objects/contacts/{contact_id}"
                _req.patch(update_url, headers=headers, json={
                    "properties": {"notes_last_updated": datetime.now().isoformat()}
                })
        except:
            pass
    
    # Return simple confirmation page
    if os.path.exists(unsub_path):
        return send_file(unsub_path)
    
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Unsubscribed</title></head>
    <body style="font-family:Arial;padding:40px;text-align:center;background:#f4f4f4;">
    <div style="background:#fff;padding:40px;border-radius:12px;max-width:400px;margin:0 auto;">
    <h2 style="color:#2ec4b6;">You're unsubscribed.</h2>
    <p style="color:#666;">You won't receive any more Franchise Focus emails.</p>
    <a href="https://smartdealer.com" style="color:#4361ee;">← Back to SmartDealer</a>
    </div></body></html>"""

# ─── Documents ───────────────────────────────────────────────────────────────

DOCS_DIR = f'{BASE_DIR}/documents'
DOCS_INDEX = f'{DOCS_DIR}/index.json'

def load_docs_index():
    if not os.path.exists(DOCS_INDEX):
        return []
    try:
        with open(DOCS_INDEX) as f:
            data = json.load(f)
        # index.json may be a dict with 'documents' key or a plain list
        if isinstance(data, dict):
            return data.get('documents', [])
        return data
    except:
        return []

def save_docs_index(docs):
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(DOCS_INDEX, 'w') as f:
        json.dump(docs, f, indent=2)

@app.route('/api/docs', methods=['GET'])
def get_docs():
    docs = load_docs_index()
    q = request.args.get('q', '').strip().lower()
    cat = request.args.get('category', '').strip()
    if q:
        docs = [d for d in docs if q in d.get('title', '').lower() or q in d.get('category', '').lower() or q in ' '.join(d.get('tags', [])).lower()]
    if cat:
        docs = [d for d in docs if d.get('category', '').lower() == cat.lower()]
    return jsonify({'documents': docs})

@app.route('/api/docs', methods=['POST'])
def create_doc():
    data = request.json or {}
    docs = load_docs_index()
    doc_id = f'doc-{datetime.now().strftime("%Y%m%d%H%M%S")}-{len(docs)}'
    content = data.get('content', '')
    doc = {
        'id': doc_id,
        'title': data.get('title', 'Untitled'),
        'category': data.get('category', 'Other'),
        'tags': data.get('tags', []),
        'format': data.get('format', 'markdown'),
        'created': datetime.now().isoformat(),
        'updated': datetime.now().isoformat(),
        'size': len(content)
    }
    # Save content to file
    os.makedirs(DOCS_DIR, exist_ok=True)
    with open(f'{DOCS_DIR}/{doc_id}.md', 'w') as f:
        f.write(content)
    docs.append(doc)
    save_docs_index(docs)
    return jsonify({'status': 'ok', 'document': doc})

@app.route('/api/docs/<doc_id>', methods=['GET'])
def get_doc(doc_id):
    docs = load_docs_index()
    doc = next((d for d in docs if d['id'] == doc_id), None)
    if not doc:
        return jsonify({'error': 'Not found'}), 404
    content = ''
    doc_file = f'{DOCS_DIR}/{doc_id}.md'
    if os.path.exists(doc_file):
        with open(doc_file) as f:
            content = f.read()
    return jsonify({**doc, 'content': content})

@app.route('/api/docs/<doc_id>', methods=['DELETE'])
def delete_doc(doc_id):
    docs = load_docs_index()
    docs = [d for d in docs if d['id'] != doc_id]
    save_docs_index(docs)
    doc_file = f'{DOCS_DIR}/{doc_id}.md'
    if os.path.exists(doc_file):
        os.remove(doc_file)
    return jsonify({'status': 'ok'})

@app.route('/api/docs/search', methods=['GET'])
def search_docs():
    q = request.args.get('q', '').strip().lower()
    if not q:
        return jsonify({'results': []})
    docs = load_docs_index()
    results = []
    for doc in docs:
        score = 0
        if q in doc.get('title', '').lower(): score += 3
        if q in doc.get('category', '').lower(): score += 1
        if any(q in t.lower() for t in doc.get('tags', [])): score += 2
        # Check content
        doc_file = f'{DOCS_DIR}/{doc["id"]}.md'
        if os.path.exists(doc_file):
            try:
                with open(doc_file) as f:
                    content = f.read().lower()
                if q in content: score += 1
            except: pass
        if score > 0:
            results.append({**doc, 'score': score})
    results.sort(key=lambda x: x['score'], reverse=True)
    return jsonify({'results': results})

# ─── Memory / Journal API ──────────────────────────────────────────────────────

MEMORY_DIR = '/Users/scottanderson/.openclaw/workspace/memory'
LONGTIME_FILE = '/Users/scottanderson/.openclaw/workspace/MEMORY.md'

def parse_daily_entry(filepath):
    """Parse a daily memory file into structured data."""
    try:
        with open(filepath) as f:
            content = f.read()
        basename = os.path.basename(filepath)
        date_str = basename.replace('.md', '')
        # Extract title / first heading
        lines = content.strip().split('\n')
        title = date_str
        summary = ''
        for line in lines:
            if line.startswith('## '):
                title = line.replace('## ', '').strip()
                break
        # Get first non-heading paragraph
        in_summary = False
        for line in lines:
            if line.startswith('## '):
                in_summary = True
                continue
            if in_summary and line.strip() and not line.startswith('#'):
                summary = line.strip()[:200]
                break
        return {
            'date': date_str,
            'title': title,
            'summary': summary,
            'has_content': len(content) > 50
        }
    except Exception as e:
        return {'date': os.path.basename(filepath), 'title': 'Error', 'summary': str(e), 'has_content': False}

@app.route('/api/memory/daily')
def memory_daily_list():
    """List all daily memory entries."""
    entries = []
    if os.path.isdir(MEMORY_DIR):
        for fname in sorted(os.listdir(MEMORY_DIR)):
            if fname.endswith('.md'):
                entry = parse_daily_entry(os.path.join(MEMORY_DIR, fname))
                entries.append(entry)
    return jsonify({'entries': entries})

@app.route('/api/memory/daily/<date_str>')
def memory_daily_entry(date_str):
    """Get full content for a specific day."""
    fpath = os.path.join(MEMORY_DIR, date_str + '.md')
    if not os.path.exists(fpath):
        return jsonify({'error': 'Not found'}), 404
    with open(fpath) as f:
        content = f.read()
    entry = parse_daily_entry(fpath)
    entry['content'] = content
    return jsonify(entry)

@app.route('/api/memory/longterm')
def memory_longterm():
    """Get long-term memory (MEMORY.md)."""
    if not os.path.exists(LONGTIME_FILE):
        return jsonify({'error': 'Not found'}), 404
    with open(LONGTIME_FILE) as f:
        content = f.read()
    # Extract sections
    sections = []
    current = {'title': 'Overview', 'content': ''}
    for line in content.split('\n'):
        if line.startswith('## '):
            if current['content']:
                sections.append(current)
            current = {'title': line.replace('## ', '').strip(), 'content': ''}
        else:
            current['content'] += line + '\n'
    if current['content']:
        sections.append(current)
    return jsonify({'content': content, 'sections': sections})

@app.route('/api/memory/search')
def memory_search():
    """Search across all memory files."""
    query = request.args.get('q', '').strip().lower()
    if not query:
        return jsonify({'results': []})
    results = []
    if os.path.isdir(MEMORY_DIR):
        for fname in sorted(os.listdir(MEMORY_DIR)):
            if fname.endswith('.md'):
                fpath = os.path.join(MEMORY_DIR, fname)
                with open(fpath) as f:
                    content = f.read()
                if query in content.lower():
                    # Find context around matches
                    lines = content.lower().split('\n')
                    matches = []
                    for i, line in enumerate(lines):
                        if query in line:
                            orig_line = content.split('\n')[i]
                            context = orig_line.strip()[:150]
                            matches.append({'line': context, 'line_num': i})
                    results.append({
                        'date': fname.replace('.md', ''),
                        'matches': matches[:5]
                    })
    return jsonify({'query': query, 'results': results})

# ─── Memory Status ───────────────────────────────────────────────────────────

@app.route('/api/memory-status')
def memory_status():
    """Return memory & dreaming system status."""
    import sqlite3
    result = {
        'files_indexed': 0, 'chunks': 0, 'recall_entries': 0,
        'dreaming_enabled': False, 'next_sweep': '3:00 AM ET',
        'workspace_files': 0
    }
    # Count workspace memory files
    mem_dir = os.path.join(BASE_DIR, 'memory')
    if os.path.isdir(mem_dir):
        result['workspace_files'] = len([f for f in os.listdir(mem_dir) if f.endswith('.md')])
    # Count key workspace files
    for f in ['MEMORY.md', 'WORKING_CONTEXT.md', 'MISTAKES.md', 'PROJECTS.md']:
        if os.path.exists(os.path.join(BASE_DIR, f)):
            result['workspace_files'] += 1
    # Read SQLite memory store
    db_path = os.path.expanduser('~/.openclaw/memory/main.sqlite')
    if os.path.exists(db_path):
        try:
            conn = sqlite3.connect(db_path, timeout=2)
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM files")
            result['files_indexed'] = cur.fetchone()[0]
            cur.execute("SELECT COUNT(*) FROM chunks")
            result['chunks'] = cur.fetchone()[0]
            conn.close()
        except:
            pass
    # Read recall store
    recall_path = os.path.join(BASE_DIR, 'memory', '.dreams', 'short-term-recall.json')
    if os.path.exists(recall_path):
        try:
            with open(recall_path) as f:
                recall = json.load(f)
            result['recall_entries'] = len(recall) if isinstance(recall, list) else len(recall.get('entries', []))
        except:
            pass
    # Check dreaming config
    oc_config = os.path.expanduser('~/.openclaw/openclaw.json')
    if os.path.exists(oc_config):
        try:
            with open(oc_config) as f:
                cfg = json.load(f)
            dreaming = cfg.get('plugins', {}).get('entries', {}).get('memory-core', {}).get('config', {}).get('dreaming', {})
            result['dreaming_enabled'] = dreaming.get('enabled', False)
            freq = dreaming.get('frequency', '0 3 * * *')
            tz = dreaming.get('timezone', 'UTC')
            result['next_sweep'] = f"{freq} ({tz})"
        except:
            pass
    return jsonify(result)

# ─── Alpaca / Investor ──────────────────────────────────────────────────────

import urllib.request as _urlreq, urllib.error as _urlerr
from pathlib import Path as _PathP

def _load_alpaca_env():
    env_path = _PathP('/Users/scottanderson/.openclaw/workspace/scripts/.env')
    keys = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            k, v = line.split('=', 1)
            keys[k.strip()] = v.strip().strip('"').strip("'")
    return keys

def _alpaca_req(path, keys, base='https://paper-api.alpaca.markets'):
    url = f"{base}{path}"
    req = _urlreq.Request(url, headers={
        'APCA-API-KEY-ID': keys.get('ALPACA_API_KEY', ''),
        'APCA-API-SECRET-KEY': keys.get('ALPACA_SECRET_KEY', ''),
    })
    try:
        resp = _urlreq.urlopen(req, timeout=10)
        return json.loads(resp.read())
    except _urlerr.HTTPError as e:
        return {'error': f'HTTP {e.code}', 'detail': e.read().decode()[:200]}
    except Exception as e:
        return {'error': str(e)}

def _f(v, default=0.0):
    try:
        return float(v) if v not in (None, '') else default
    except (ValueError, TypeError):
        return default

@app.route('/api/portfolio')
def api_portfolio():
    keys = _load_alpaca_env()
    if not keys.get('ALPACA_API_KEY'):
        return jsonify({'error': 'ALPACA_API_KEY not configured'}), 500

    account = _alpaca_req('/v2/account', keys)
    positions = _alpaca_req('/v2/positions', keys)
    orders = _alpaca_req('/v2/orders?status=all&limit=20', keys)

    equity = _f(account.get('equity'))
    last_equity = _f(account.get('last_equity'))
    today_pnl = equity - last_equity
    today_pct = (today_pnl / last_equity * 100) if last_equity else 0

    snapshot = {
        'account': {
            'equity': equity,
            'cash': _f(account.get('cash')),
            'buying_power': _f(account.get('buying_power')),
            'portfolio_value': _f(account.get('portfolio_value')),
            'long_market_value': _f(account.get('long_market_value')),
            'short_market_value': _f(account.get('short_market_value')),
            'status': account.get('status', 'unknown'),
            'mode': 'PAPER',
            'today_pnl': today_pnl,
            'today_pct': today_pct,
        },
        'positions': [
            {
                'symbol': p.get('symbol'),
                'qty': _f(p.get('qty')),
                'side': p.get('side'),
                'avg_entry_price': _f(p.get('avg_entry_price')),
                'current_price': _f(p.get('current_price')),
                'market_value': _f(p.get('market_value')),
                'cost_basis': _f(p.get('cost_basis')),
                'unrealized_pl': _f(p.get('unrealized_pl')),
                'unrealized_plpc': _f(p.get('unrealized_plpc')) * 100,
                'change_today': _f(p.get('change_today')) * 100,
            }
            for p in (positions if isinstance(positions, list) else [])
        ],
        'orders': [
            {
                'id': o.get('id'),
                'symbol': o.get('symbol'),
                'qty': _f(o.get('qty')),
                'side': o.get('side'),
                'type': o.get('type'),
                'status': o.get('status'),
                'filled_avg_price': _f(o.get('filled_avg_price')),
                'submitted_at': o.get('submitted_at'),
                'filled_at': o.get('filled_at'),
            }
            for o in (orders if isinstance(orders, list) else [])
        ],
    }
    return jsonify(snapshot)

@app.route('/api/portfolio/history')
def api_portfolio_history():
    keys = _load_alpaca_env()
    if not keys.get('ALPACA_API_KEY'):
        return jsonify({'error': 'ALPACA_API_KEY not configured'}), 500
    data = _alpaca_req('/v2/account/portfolio/history?period=1M&timeframe=1D', keys)
    return jsonify(data)

# ─── Start ───────────────────────────────────────────────────────────────────

# ─── Wheel Strategy Dashboard ──────────────────────────────────────────────
import pathlib
WHEEL_DIR = pathlib.Path('/Users/scottanderson/.openclaw/workspace/memory/wheel')
WHEEL_SKILL = pathlib.Path('/Users/scottanderson/.openclaw/workspace/scripts/skills/wheel-strategy')


def _read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    with path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


@app.route('/api/wheel/summary')
def api_wheel_summary():
    """Aggregate stats from the wheel trade journal + latest backtest + sweep."""
    trades = _read_jsonl(WHEEL_DIR / 'trades.jsonl')
    sim = [t for t in trades if t.get('action') == 'simulated']
    sub = [t for t in trades if t.get('action') == 'submitted']
    blk = [t for t in trades
           if str(t.get('action', '')).startswith('blocked')
           or str(t.get('action', '')).startswith('submit_failed')]

    latest_bt = None
    bt_files = sorted(WHEEL_DIR.glob('backtest_*.json'), reverse=True)
    if bt_files:
        try:
            latest_bt = json.loads(bt_files[0].read_text())
        except json.JSONDecodeError:
            pass

    sweep_files = sorted(WHEEL_DIR.glob('sweep_*.json'), reverse=True)
    latest_sweep = None
    if sweep_files:
        try:
            latest_sweep = json.loads(sweep_files[0].read_text())
        except json.JSONDecodeError:
            pass

    open_positions = []
    pos_file = WHEEL_DIR / 'positions.json'
    if pos_file.exists():
        try:
            pos_data = json.loads(pos_file.read_text())
            open_positions = [p for p in pos_data.get('positions', [])
                              if p.get('state') not in ('NONE', 'CLOSED')]
        except json.JSONDecodeError:
            pass

    return jsonify({
        'mode': 'PAPER',
        'journal': {
            'total_entries': len(trades),
            'simulated': len(sim),
            'submitted': len(sub),
            'blocked_or_failed': len(blk),
            'last_event': trades[-1] if trades else None,
        },
        'open_positions': open_positions,
        'latest_backtest': latest_bt,
        'latest_sweep': latest_sweep,
    })


@app.route('/api/wheel/trades')
def api_wheel_trades():
    trades = _read_jsonl(WHEEL_DIR / 'trades.jsonl')
    return jsonify({'trades': trades[-200:]})


@app.route('/api/wheel/calibration')
def api_wheel_calibration():
    """Predicted vs realized outcomes. Drives the learning loop."""
    trades = _read_jsonl(WHEEL_DIR / 'trades.jsonl')
    opens = {}
    closed = []
    for t in trades:
        sym = t.get('occ_symbol')
        action = str(t.get('action', ''))
        side = str(((t.get('payload') or {}).get('ticket') or {}).get('side', ''))
        if not sym:
            continue
        if action in ('simulated', 'submitted') and 'open' in side:
            opens[sym] = t
        elif action in ('simulated', 'submitted') and 'close' in side:
            if sym in opens:
                closed.append({'open': opens.pop(sym), 'close': t})

    win_rate = None
    if closed:
        wins = sum(
            1 for c in closed
            if 'profit' in str(c['close'].get('reason', ''))
            or 'expired_otm' in str(c['close'].get('reason', ''))
        )
        win_rate = round(100 * wins / len(closed), 1)

    return jsonify({
        'closed_trades': len(closed),
        'open_positions': len(opens),
        'win_rate_pct': win_rate,
        'recommendation': (
            'collect 30+ closed trades before re-calibrating thresholds'
            if (not closed or len(closed) < 30)
            else 'enough data — re-run calibration sweep'
        ),
        'pairs': closed[-50:],
    })


@app.route('/api/wheel/config')
def api_wheel_config():
    cfg_file = WHEEL_SKILL / 'config.yaml'
    if not cfg_file.exists():
        return jsonify({'error': 'config.yaml not found'}), 404
    try:
        cfg = yaml.safe_load(cfg_file.read_text())
        return jsonify(cfg)
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/wheel')
def wheel_dashboard():
    dash = pathlib.Path(__file__).parent / 'wheel.html'
    if dash.exists():
        return dash.read_text()
    return '<h1>Wheel dashboard not yet built</h1>', 404

# ─── Politician Signal endpoints (read-only) ──────────────────────
POL_SIG_DIR = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/politician_signal'
)


def _read_json_safe(path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return default


@app.route('/api/wheel/politicians/summary')
def api_politician_summary():
    latest = _read_json_safe(POL_SIG_DIR / 'latest.json', default={}) or {}
    bt = _read_json_safe(POL_SIG_DIR / 'backtest.json', default={}) or {}
    weekly = sorted(POL_SIG_DIR.glob('trades_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    last_snap = weekly[0].name if weekly else None
    tickers = latest.get('tickers', [])
    top5 = [
        {'symbol': r['symbol'], 'score': r['score'],
         'buy_count': r['buy_count'], 'sell_count': r['sell_count'],
         'politicians': r['politicians'][:3]}
        for r in tickers[:5]
    ]
    return jsonify({
        'generated_at': latest.get('generated_at'),
        'lookback_days': latest.get('lookback_days'),
        'ticker_count': latest.get('ticker_count', 0),
        'top_5': top5,
        'last_weekly_snapshot': last_snap,
        'backtest_generated_at': bt.get('generated_at'),
        'backtest_30d_excess': bt.get('excess_return_vs_spy', {}).get('30d'),
        'backtest_spy_return': bt.get('spy_return'),
        'high_score_count': sum(1 for r in tickers if r.get('score', 0) >= 5.0),
    })


@app.route('/api/wheel/politicians/trades')
def api_politician_trades():
    weekly = sorted(POL_SIG_DIR.glob('trades_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not weekly:
        return jsonify({'trades': [], 'snapshot': None})
    data = _read_json_safe(weekly[0], default={}) or {}
    trades = data.get('trades', [])
    # newest first
    trades.sort(key=lambda t: t.get('trade_date', ''), reverse=True)
    return jsonify({
        'snapshot': weekly[0].name,
        'generated_at': data.get('generated_at'),
        'count': len(trades),
        'trades': trades[:200],
    })


@app.route('/api/wheel/politicians/scoring')
def api_politician_scoring():
    return jsonify(_read_json_safe(POL_SIG_DIR / 'latest.json',
                                   default={'error': 'latest.json missing'}))


@app.route('/api/wheel/politicians/backtest')
def api_politician_backtest():
    bt = _read_json_safe(POL_SIG_DIR / 'backtest.json',
                         default={'error': 'backtest.json missing'})
    return jsonify(bt)


# ─── Top-Trader Signal endpoints (read-only) ─────────────────
TOP_TRADER_DIR = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/top_trader_signal'
)


@app.route('/api/wheel/top-trader/summary')
def api_top_trader_summary():
    latest = _read_json_safe(TOP_TRADER_DIR / 'latest.json', default={}) or {}
    bt = _read_json_safe(TOP_TRADER_DIR / 'backtest.json', default={}) or {}
    weekly = sorted(TOP_TRADER_DIR.glob('holdings_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    last_snap = weekly[0].name if weekly else None
    tickers = latest.get('tickers', [])
    top5 = [
        {'symbol': r['symbol'], 'score': r['score'],
         'new_buy_count': r.get('new_buy_count', 0),
         'added_count': r.get('added_count', 0),
         'trimmed_count': r.get('trimmed_count', 0),
         'exited_count': r.get('exited_count', 0),
         'fund_ciks': r.get('fund_ciks', [])[:5]}
        for r in tickers[:5]
    ]
    return jsonify({
        'generated_at': latest.get('generated_at'),
        'lookback_days': latest.get('lookback_days'),
        'ticker_count': latest.get('ticker_count', 0),
        'top_5': top5,
        'last_weekly_snapshot': last_snap,
        'backtest_generated_at': bt.get('generated_at'),
        'backtest_30d_excess': bt.get('excess_return_vs_spy', {}).get('30d'),
        'backtest_spy_return': bt.get('spy_return'),
        'high_score_count': sum(1 for r in tickers if r.get('score', 0) >= 8.0),
    })


@app.route('/api/wheel/top-trader/trades')
def api_top_trader_trades():
    weekly = sorted(TOP_TRADER_DIR.glob('holdings_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not weekly:
        return jsonify({'trades': [], 'snapshot': None})
    data = _read_json_safe(weekly[0], default={}) or {}
    trades = data.get('trades', [])
    trades.sort(key=lambda t: t.get('filed_date', ''), reverse=True)
    return jsonify({
        'snapshot': weekly[0].name,
        'generated_at': data.get('generated_at'),
        'count': len(trades),
        'trades': trades[:200],
    })


@app.route('/api/wheel/top-trader/scoring')
def api_top_trader_scoring():
    return jsonify(_read_json_safe(TOP_TRADER_DIR / 'latest.json',
                                   default={'error': 'latest.json missing'}))


@app.route('/api/wheel/top-trader/backtest')
def api_top_trader_backtest():
    bt = _read_json_safe(TOP_TRADER_DIR / 'backtest.json',
                         default={'error': 'backtest.json missing'})
    return jsonify(bt)


# ─── Analyst Signal endpoints (read-only) ─────────────────
ANL_SIG_DIR = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/analyst_signal'
)


@app.route('/api/wheel/analysts/summary')
def api_analyst_summary():
    latest = _read_json_safe(ANL_SIG_DIR / 'latest.json', default={}) or {}
    bt = _read_json_safe(ANL_SIG_DIR / 'backtest.json', default={}) or {}
    snaps = sorted(ANL_SIG_DIR.glob('snapshot_*.json'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    last_snap = snaps[0].name if snaps else None
    tickers = latest.get('tickers', [])
    top10 = [
        {'symbol': r['symbol'], 'score': r['score'],
         'net_buy_ratio': r['net_buy_ratio'],
         'momentum': r['momentum'],
         'upside_pct': r['upside_pct'],
         'analyst_count': r['analyst_count'],
         'sector': r.get('sector')}
        for r in tickers[:10]
    ]
    return jsonify({
        'generated_at': latest.get('generated_at'),
        'lookback_days': latest.get('lookback_days'),
        'ticker_count': latest.get('ticker_count', 0),
        'skipped_count': latest.get('skipped_count', 0),
        'extend_threshold': latest.get('extend_threshold', 8.0),
        'blacklist_threshold': latest.get('blacklist_threshold', -3.0),
        'top_10': top10,
        'blacklist': latest.get('blacklist', []),
        'last_weekly_snapshot': last_snap,
        'backtest_generated_at': bt.get('generated_at'),
        'backtest_30d_excess': bt.get('excess_return_vs_spy', {}).get('30d'),
        'backtest_spy_return': bt.get('spy_return'),
        'high_score_count': sum(1 for r in tickers if r.get('score', 0) >= 8.0),
    })


@app.route('/api/wheel/analysts/scoring')
def api_analyst_scoring():
    return jsonify(_read_json_safe(ANL_SIG_DIR / 'latest.json',
                                   default={'error': 'latest.json missing'}))


@app.route('/api/wheel/analysts/snapshots')
def api_analyst_snapshots():
    snaps = sorted(ANL_SIG_DIR.glob('snapshot_*.json'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not snaps:
        return jsonify({'snapshots_available': [], 'latest': None})
    data = _read_json_safe(snaps[0], default={}) or {}
    return jsonify({
        'latest': snaps[0].name,
        'generated_at': data.get('generated_at'),
        'count': data.get('count', 0),
        'iso_year': data.get('iso_year'),
        'iso_week': data.get('iso_week'),
        'snapshots_available': [p.name for p in snaps[:12]],
    })


@app.route('/api/wheel/analysts/backtest')
def api_analyst_backtest():
    bt = _read_json_safe(ANL_SIG_DIR / 'backtest.json',
                         default={'error': 'backtest.json missing'})
    return jsonify(bt)


# ─── News-Sentiment Signal endpoints (read-only) ──────────────
NEWS_SIG_DIR = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/news_sentiment_signal'
)


@app.route('/api/wheel/news/summary')
def api_news_summary():
    latest = _read_json_safe(NEWS_SIG_DIR / 'latest.json', default={}) or {}
    bt = _read_json_safe(NEWS_SIG_DIR / 'backtest.json', default={}) or {}
    weekly = sorted(NEWS_SIG_DIR.glob('headlines_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    last_snap = weekly[0].name if weekly else None
    tickers = latest.get('tickers', []) or []
    blacklist = latest.get('blacklist', []) or []
    top5 = [
        {'symbol': r['symbol'], 'score': r['score'],
         'mention_count': r['mention_count'],
         'positive_count': r['positive_count'],
         'negative_count': r['negative_count'],
         'weighted_polarity': r['weighted_polarity']}
        for r in tickers[:5]
    ]
    pos_30 = (bt.get('positive_cohort') or {}).get(
        'excess_return_vs_spy', {}).get('30d') or {}
    neg_30 = (bt.get('blacklist_cohort') or {}).get(
        'underperformance_vs_spy', {}).get('30d') or {}
    return jsonify({
        'generated_at': latest.get('generated_at'),
        'lookback_days': latest.get('lookback_days'),
        'headline_count': latest.get('headline_count', 0),
        'positive_ticker_count': len(tickers),
        'blacklist_count': len(blacklist),
        'top_5_positive': top5,
        'top_5_blacklist': [
            {'symbol': b['symbol'], 'score': b['score'],
             'reason': b.get('reason', '')} for b in blacklist[:5]
        ],
        'last_weekly_snapshot': last_snap,
        'backtest_generated_at': bt.get('generated_at'),
        'backtest_positive_30d_excess': pos_30,
        'backtest_blacklist_30d_underperf': neg_30,
    })


@app.route('/api/wheel/news/headlines')
def api_news_headlines():
    weekly = sorted(NEWS_SIG_DIR.glob('headlines_*.json'),
                    key=lambda p: p.stat().st_mtime, reverse=True)
    if not weekly:
        return jsonify({'headlines': [], 'snapshot': None})
    data = _read_json_safe(weekly[0], default={}) or {}
    rows = data.get('headlines', []) or []
    rows.sort(key=lambda h: h.get('published_at', ''), reverse=True)
    return jsonify({
        'snapshot': weekly[0].name,
        'generated_at': data.get('generated_at'),
        'count': len(rows),
        'headlines': rows[:200],
    })


@app.route('/api/wheel/news/scoring')
def api_news_scoring():
    return jsonify(_read_json_safe(NEWS_SIG_DIR / 'latest.json',
                                   default={'error': 'latest.json missing'}))


@app.route('/api/wheel/news/backtest')
def api_news_backtest():
    bt = _read_json_safe(NEWS_SIG_DIR / 'backtest.json',
                         default={'error': 'backtest.json missing'})
    return jsonify(bt)


# ─── Forecaster (composite scoring) endpoints ────────────────────────────
FORECASTER_DIR = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/forecaster'
)
FORECASTER_SEED = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/scripts/skills/'
    'forecaster/references/default_weights.json'
)


@app.route('/api/wheel/forecaster/summary')
def api_forecaster_summary():
    latest = _read_json_safe(FORECASTER_DIR / 'latest.json', default={}) or {}
    bt = _read_json_safe(FORECASTER_DIR / 'backtest.json', default={}) or {}
    snaps = sorted(FORECASTER_DIR.glob('snapshot_*.json'),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    last_snap = snaps[0].name if snaps else None
    tickers = latest.get('tickers', []) or []
    top5 = [
        {'symbol': r['symbol'], 'score': r['score'],
         'score_raw': r.get('score_raw'),
         'agreement_bonus': r.get('agreement_bonus'),
         'sources': r.get('sources', []),
         'components': r.get('components', {})}
        for r in tickers[:5]
    ]
    return jsonify({
        'generated_at': latest.get('generated_at'),
        'active_sources': latest.get('active_sources', []),
        'weights_used': latest.get('weights_used', {}),
        'calibration': latest.get('calibration', {}),
        'ticker_count': latest.get('ticker_count', 0),
        'above_threshold_5': sum(1 for r in tickers if r.get('score', 0) >= 5.0),
        'top_5': top5,
        'blacklist_count': len(latest.get('blacklist', []) or []),
        'last_weekly_snapshot': last_snap,
        'backtest_generated_at': bt.get('generated_at'),
        'backtest_verdict': bt.get('verdict'),
        'diagnostics': latest.get('diagnostics', []),
    })


@app.route('/api/wheel/forecaster/scoring')
def api_forecaster_scoring():
    return jsonify(_read_json_safe(FORECASTER_DIR / 'latest.json',
                                   default={'error': 'latest.json missing'}))


@app.route('/api/wheel/forecaster/weights')
def api_forecaster_weights():
    seed = _read_json_safe(FORECASTER_SEED, default={}) or {}
    override = _read_json_safe(FORECASTER_DIR / 'weights_override.json',
                               default=None)
    latest = _read_json_safe(FORECASTER_DIR / 'latest.json', default={}) or {}
    return jsonify({
        'seed_weights': seed,
        'override_active': override is not None,
        'override_weights': override,
        'weights_used_last_run': latest.get('weights_used', {}),
        'calibration': latest.get('calibration', {}),
    })


@app.route('/api/wheel/forecaster/backtest')
def api_forecaster_backtest():
    bt = _read_json_safe(FORECASTER_DIR / 'backtest.json',
                         default={'error': 'backtest.json missing'})
    return jsonify(bt)


# ─── Investor Engine (master dashboard aggregator) ───────────────────────
# Single composite endpoint + Alpaca proxy + auto-insights + candidate names.
# Server-side TTL cache keeps round-trips cheap.
import time as _time
import re as _re
from collections import defaultdict as _ddict

_IE_CACHE = {}  # key -> (expires_ts, payload)

# Wheel paper-account starting capital (single source of truth).
# When flipping to live, append a new entry in memory/wheel/account_ledger.json.
WHEEL_STARTING_CAPITAL = 100000
ACCOUNT_LEDGER_FILE = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/wheel/account_ledger.json'
)
EOD_LOG_FILE = pathlib.Path(
    '/Users/scottanderson/.openclaw/workspace/memory/wheel/eod_log.jsonl'
)


def _ie_cache_get(key, ttl_sec, builder):
    now = _time.time()
    ent = _IE_CACHE.get(key)
    if ent and ent[0] > now:
        return ent[1]
    payload = builder()
    _IE_CACHE[key] = (now + ttl_sec, payload)
    return payload


def _load_account_ledger():
    """Return ledger dict; bootstrap default if missing."""
    if ACCOUNT_LEDGER_FILE.exists():
        try:
            return json.loads(ACCOUNT_LEDGER_FILE.read_text())
        except json.JSONDecodeError:
            pass
    return {
        'accounts': [{
            'id': 'paper-2026-05-12', 'type': 'paper',
            'alpaca_account_id': 'PA328D2MBAK9',
            'starting_capital': WHEEL_STARTING_CAPITAL,
            'started_at': '2026-05-12T13:00:00Z',
            'ended_at': None, 'deposits': [], 'withdrawals': [],
        }],
        'active_account_id': 'paper-2026-05-12',
    }


def _active_account():
    led = _load_account_ledger()
    aid = led.get('active_account_id')
    for a in led.get('accounts', []):
        if a.get('id') == aid:
            return a
    return led.get('accounts', [{}])[0] if led.get('accounts') else {}


def _strip_occ(sym):
    if not sym:
        return ''
    m = _re.match(r'^([A-Z\.]{1,6})\d{6}[CP]\d+$', sym)
    return m.group(1) if m else sym


def _parse_occ(sym):
    if not sym:
        return None
    m = _re.match(r'^([A-Z\.]{1,6})(\d{2})(\d{2})(\d{2})([CP])(\d{8})$', sym)
    if not m:
        return None
    und, yy, mm, dd, cp, strike8 = m.groups()
    return und, f"20{yy}-{mm}-{dd}", cp, int(strike8) / 1000.0


def _holding_days(open_ts, close_ts):
    try:
        a = datetime.fromisoformat((open_ts or '').replace('Z', '+00:00'))
        b = datetime.fromisoformat((close_ts or '').replace('Z', '+00:00'))
        return (b - a).days
    except Exception:
        return None


def _walk_wheel_trades_for_pnl(trades=None):
    """
    Walk trades.jsonl and compute multi-axis P&L.

    Conventions (Scott's spec):
      sell_to_open  → +credit (premium_gross AND premium_net)
      buy_to_close  → -debit  (spend; reduces premium_net; realizes credit-debit)
      expired_otm   → realizes full credit kept
      assigned      → realized = 0 (rolls into stock cost basis)
      called_away   → realized = call_premium + (strike - stock_cost_basis) * 100

    Treats `action == 'submitted'` (paper) as filled — Alpaca paper fills sells fast.
    Skips pure `simulated` (dry-run) — never hit market.

    Returns: realized, premium_gross, premium_net, spend, open_premium_at_risk,
    wins, losses, by_month, by_year, closed_cycles, open_legs_count.
    """
    if trades is None:
        trades = _read_jsonl(WHEEL_DIR / 'trades.jsonl')

    realized = premium_gross = premium_net = spend = open_at_risk = 0.0
    wins = losses = 0

    by_month = _ddict(lambda: {
        'realized': 0.0, 'premium_gross': 0.0, 'premium_net': 0.0,
        'spend': 0.0, 'wins': 0, 'losses': 0, 'trades': 0,
    })
    by_year = _ddict(lambda: {
        'realized': 0.0, 'premium_gross': 0.0, 'premium_net': 0.0,
        'spend': 0.0, 'wins': 0, 'losses': 0, 'trades': 0,
    })
    open_legs = {}
    closed_cycles = []

    for t in trades:
        action = (t.get('action') or '').lower()
        ts = t.get('ts') or t.get('timestamp') or t.get('timestamp_utc') or ''
        ymd = ts[:10] if ts else ''
        ym = ymd[:7]
        yr = ymd[:4]
        ticket = (t.get('payload') or {}).get('ticket') or {}
        side = (ticket.get('side') or '').lower()
        qty = abs(float(ticket.get('qty') or t.get('qty') or 1))
        price = float(ticket.get('limit_price') or t.get('price') or 0)
        occ = t.get('occ_symbol') or t.get('contract') or ticket.get('occ_symbol')
        underlying = t.get('underlying') or t.get('symbol') or _strip_occ(occ)
        parsed = _parse_occ(occ) if occ else None
        strike = (parsed[3] if parsed else 0) or 0

        is_real = (action == 'submitted' or action == 'filled' or action == 'closed'
                   or action.startswith('expired') or action.startswith('assigned')
                   or action.startswith('called_away'))
        if not is_real:
            continue

        by_month[ym]['trades'] += 1
        by_year[yr]['trades'] += 1

        if 'sell_to_open' in side or action == 'sell_to_open':
            credit = price * qty * 100
            premium_gross += credit
            premium_net += credit
            by_month[ym]['premium_gross'] += credit
            by_month[ym]['premium_net'] += credit
            by_year[yr]['premium_gross'] += credit
            by_year[yr]['premium_net'] += credit
            if occ:
                open_legs[occ] = {'credit': credit, 'qty': qty,
                                  'open_ts': ts, 'strike': strike,
                                  'underlying': underlying}
                open_at_risk += strike * qty * 100
        elif 'buy_to_close' in side or action == 'buy_to_close':
            debit = price * qty * 100
            spend += debit
            premium_net -= debit
            by_month[ym]['spend'] += debit
            by_month[ym]['premium_net'] -= debit
            by_year[yr]['spend'] += debit
            by_year[yr]['premium_net'] -= debit
            leg = open_legs.pop(occ, None) if occ else None
            if leg:
                pnl = leg['credit'] - debit
                realized += pnl
                by_month[ym]['realized'] += pnl
                by_year[yr]['realized'] += pnl
                open_at_risk -= leg['strike'] * leg['qty'] * 100
                if pnl >= 0:
                    wins += 1
                    by_month[ym]['wins'] += 1
                    by_year[yr]['wins'] += 1
                else:
                    losses += 1
                    by_month[ym]['losses'] += 1
                    by_year[yr]['losses'] += 1
                closed_cycles.append({
                    'symbol': leg.get('underlying') or _strip_occ(occ),
                    'occ_symbol': occ,
                    'open_date': (leg.get('open_ts') or '')[:10],
                    'close_date': ymd,
                    'premium_credit': leg['credit'],
                    'close_debit': debit,
                    'realized_pnl': pnl,
                    'holding_period_days': _holding_days(leg.get('open_ts'), ts),
                    'outcome': 'closed_for_profit' if pnl >= 0 else 'closed_for_loss',
                })
        elif action.startswith('expired') or 'expired' in side:
            leg = open_legs.pop(occ, None) if occ else None
            if leg:
                pnl = leg['credit']
                realized += pnl
                by_month[ym]['realized'] += pnl
                by_year[yr]['realized'] += pnl
                open_at_risk -= leg['strike'] * leg['qty'] * 100
                wins += 1
                by_month[ym]['wins'] += 1
                by_year[yr]['wins'] += 1
                closed_cycles.append({
                    'symbol': leg.get('underlying') or _strip_occ(occ),
                    'occ_symbol': occ,
                    'open_date': (leg.get('open_ts') or '')[:10],
                    'close_date': ymd,
                    'premium_credit': leg['credit'], 'close_debit': 0.0,
                    'realized_pnl': pnl,
                    'holding_period_days': _holding_days(leg.get('open_ts'), ts),
                    'outcome': 'expired_otm',
                })
        elif action.startswith('assigned'):
            leg = open_legs.pop(occ, None) if occ else None
            if leg:
                open_at_risk -= leg['strike'] * leg['qty'] * 100
                closed_cycles.append({
                    'symbol': leg.get('underlying') or _strip_occ(occ),
                    'occ_symbol': occ,
                    'open_date': (leg.get('open_ts') or '')[:10],
                    'close_date': ymd,
                    'premium_credit': leg['credit'], 'close_debit': 0.0,
                    'realized_pnl': 0.0,
                    'holding_period_days': _holding_days(leg.get('open_ts'), ts),
                    'outcome': 'assigned',
                })
        elif action.startswith('called_away'):
            cb = float(t.get('stock_cost_basis')
                       or (t.get('payload') or {}).get('stock_cost_basis')
                       or strike)
            pnl = (price * qty * 100) + (strike - cb) * 100 * qty
            realized += pnl
            by_month[ym]['realized'] += pnl
            by_year[yr]['realized'] += pnl
            if pnl >= 0:
                wins += 1
                by_month[ym]['wins'] += 1
                by_year[yr]['wins'] += 1
            else:
                losses += 1
                by_month[ym]['losses'] += 1
                by_year[yr]['losses'] += 1
            closed_cycles.append({
                'symbol': underlying or _strip_occ(occ),
                'occ_symbol': occ, 'open_date': '', 'close_date': ymd,
                'premium_credit': price * qty * 100, 'close_debit': 0.0,
                'realized_pnl': pnl, 'holding_period_days': None,
                'outcome': 'called_away',
            })

    return {
        'realized': realized,
        'premium_gross': premium_gross,
        'premium_net': premium_net,
        'spend': spend,
        'open_premium_at_risk': max(0.0, open_at_risk),
        'wins': wins, 'losses': losses,
        'closed_cycles': closed_cycles,
        'by_month': dict(by_month), 'by_year': dict(by_year),
        'open_legs_count': len(open_legs),
    }


def _yesterday_close_equity():
    """Read last EOD snapshot strictly before today. None if missing."""
    if not EOD_LOG_FILE.exists():
        return None
    last_eq = None
    today = datetime.utcnow().strftime('%Y-%m-%d')
    with EOD_LOG_FILE.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get('date') and row['date'] < today:
                last_eq = row.get('equity')
    return last_eq


def _read_eod_log():
    """Return list of {date, equity} rows for equity curve."""
    rows = []
    if EOD_LOG_FILE.exists():
        with EOD_LOG_FILE.open() as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                    if 'date' in r and 'equity' in r:
                        rows.append({'date': r['date'], 'equity': float(r['equity'])})
                except json.JSONDecodeError:
                    continue
    return sorted(rows, key=lambda x: x['date'])


def _signal_block(latest_path, threshold, label, emoji, score_field='score'):
    """Generic shape for the signal-health strip."""
    data = _read_json_safe(latest_path, default={}) or {}
    tickers = data.get('tickers', []) or []
    above = [t for t in tickers if t.get(score_field, 0) >= threshold]
    top3 = [
        {'symbol': t.get('symbol'), 'score': t.get(score_field, 0)}
        for t in tickers[:3]
    ]
    return {
        'label': label,
        'emoji': emoji,
        'generated_at': data.get('generated_at'),
        'ticker_count': len(tickers),
        'threshold': threshold,
        'above_threshold': len(above),
        'top_3': top3,
        'blacklist_count': len(data.get('blacklist', []) or []),
    }


def _ie_build_alpaca():
    keys = _load_alpaca_env()
    if not keys.get('ALPACA_API_KEY'):
        return {'error': 'ALPACA_API_KEY not configured',
                'starting_capital': WHEEL_STARTING_CAPITAL}
    account = _alpaca_req('/v2/account', keys)
    positions = _alpaca_req('/v2/positions', keys) or []
    open_orders = _alpaca_req('/v2/orders?status=open&limit=50', keys) or []
    clock = _alpaca_req('/v2/clock', keys) or {}
    today_orders = _alpaca_req(
        '/v2/orders?status=all&limit=50&after='
        + datetime.utcnow().strftime('%Y-%m-%dT00:00:00Z'),
        keys,
    ) or []

    equity = _f(account.get('equity')) if isinstance(account, dict) else 0.0
    last_equity = _f(account.get('last_equity')) if isinstance(account, dict) else 0.0

    # ── Starting capital + total net P&L (from ledger) ───────────────
    active = _active_account()
    starting_capital = float(
        active.get('starting_capital') or WHEEL_STARTING_CAPITAL
    )
    total_pnl_dollars = equity - starting_capital
    total_pnl_pct = (total_pnl_dollars / starting_capital * 100) if starting_capital else 0.0

    # ── Today's P&L (yesterday EOD if available, else fall back to starting) ──
    yest = _yesterday_close_equity()
    baseline = yest if yest is not None else (last_equity or starting_capital)
    today_pnl_dollars = equity - baseline
    today_pnl_pct = (today_pnl_dollars / baseline * 100) if baseline else 0.0

    pos_list = positions if isinstance(positions, list) else []
    unrealized_pnl = sum(_f(p.get('unrealized_pl')) for p in pos_list)

    # ── P&L walker over trades.jsonl ─────────────────────────────────
    pnl = _walk_wheel_trades_for_pnl()

    # Sector exposure (by underlying)
    cfg_file = WHEEL_SKILL / 'config.yaml'
    sectors_map = {}
    if cfg_file.exists():
        try:
            sectors_map = (yaml.safe_load(cfg_file.read_text()) or {}).get('sectors', {}) or {}
        except Exception:
            pass
    sector_exposure = {}
    for p in pos_list:
        u = _strip_occ(p.get('symbol', ''))
        sec = sectors_map.get(u, 'Other')
        sector_exposure[sec] = sector_exposure.get(sec, 0.0) + _f(p.get('market_value'))

    # Equity curve (EOD log + today's point)
    eod = _read_eod_log()
    today = datetime.utcnow().strftime('%Y-%m-%d')
    if not eod or eod[-1]['date'] != today:
        eod = eod + [{'date': today, 'equity': equity}]

    return {
        'account': {
            'equity': equity,
            'cash': _f(account.get('cash')) if isinstance(account, dict) else 0,
            'options_buying_power': _f(account.get('options_buying_power')) if isinstance(account, dict) else 0,
            'buying_power': _f(account.get('buying_power')) if isinstance(account, dict) else 0,
            'portfolio_value': _f(account.get('portfolio_value')) if isinstance(account, dict) else 0,
            'last_equity': last_equity,
            'status': (account or {}).get('status', 'unknown'),
            'account_number': (account or {}).get('account_number', ''),
            'account_id': active.get('id'),
            'account_type': active.get('type', 'paper'),
        },
        # ── Headline P&L numbers (Scott's spec) ─────────────────────
        'starting_capital': starting_capital,
        'total_pnl_dollars': total_pnl_dollars,
        'total_pnl_pct': total_pnl_pct,
        'today_pnl_dollars': today_pnl_dollars,
        'today_pnl_pct': today_pnl_pct,
        'realized_pnl': pnl['realized'],
        'unrealized_pnl': unrealized_pnl,
        'open_premium_at_risk': pnl['open_premium_at_risk'],
        'premium_collected_gross': pnl['premium_gross'],
        'premium_collected_net': pnl['premium_net'],
        'wins_lifetime': pnl['wins'],
        'losses_lifetime': pnl['losses'],
        # ── Position detail ────────────────────────────────────────
        'positions': [
            {
                'symbol': p.get('symbol'),
                'underlying': _strip_occ(p.get('symbol', '')),
                'qty': _f(p.get('qty')),
                'side': p.get('side'),
                'avg_entry_price': _f(p.get('avg_entry_price')),
                'current_price': _f(p.get('current_price')),
                'market_value': _f(p.get('market_value')),
                'cost_basis': _f(p.get('cost_basis')),
                'unrealized_pl': _f(p.get('unrealized_pl')),
                'unrealized_plpc': _f(p.get('unrealized_plpc')) * 100,
            }
            for p in pos_list
        ],
        'open_orders': [
            {
                'id': o.get('id'), 'symbol': o.get('symbol'),
                'qty': _f(o.get('qty')), 'side': o.get('side'),
                'type': o.get('type'), 'status': o.get('status'),
                'submitted_at': o.get('submitted_at'),
                'expires_at': o.get('expires_at'),
                'limit_price': _f(o.get('limit_price')),
            }
            for o in (open_orders if isinstance(open_orders, list) else [])
        ],
        'today_orders_count': len(today_orders) if isinstance(today_orders, list) else 0,
        'sector_market_value': sector_exposure,
        'positions_count': len(pos_list),
        'open_orders_count': len(open_orders) if isinstance(open_orders, list) else 0,
        'market_is_open': bool(clock.get('is_open')) if isinstance(clock, dict) else False,
        'market_next_open': clock.get('next_open') if isinstance(clock, dict) else None,
        'market_next_close': clock.get('next_close') if isinstance(clock, dict) else None,
        'equity_curve': eod,
        'eod_log_present': EOD_LOG_FILE.exists(),
        'cached_at': datetime.utcnow().isoformat() + 'Z',
    }


def _ie_build_candidates():
    """Composite picks above threshold but NOT in wheel universe."""
    latest = _read_json_safe(FORECASTER_DIR / 'latest.json', default={}) or {}
    tickers = latest.get('tickers', []) or []
    threshold = (latest.get('calibration') or {}).get('threshold', 5.0)

    cfg_file = WHEEL_SKILL / 'config.yaml'
    universe = []
    sectors_map = {}
    if cfg_file.exists():
        try:
            cfg = yaml.safe_load(cfg_file.read_text())
            universe = cfg.get('universe', []) or []
            sectors_map = cfg.get('sectors', {}) or {}
        except Exception:
            pass
    universe_set = set(universe)

    in_uni = []
    out_of_uni = []
    for t in tickers:
        sym = t.get('symbol')
        score = t.get('score', 0)
        row = {
            'symbol': sym,
            'score': score,
            'score_raw': t.get('score_raw'),
            'sources': t.get('sources', []),
            'components': t.get('components', {}),
            'sector': sectors_map.get(sym, 'Unknown'),
            'in_universe': sym in universe_set,
        }
        if sym in universe_set:
            in_uni.append(row)
        else:
            out_of_uni.append(row)

    # Top 10 composite picks (any) — ordered by score
    top10 = sorted(tickers, key=lambda r: r.get('score', 0), reverse=True)[:10]
    top10_rows = [
        {
            'symbol': r.get('symbol'),
            'score': r.get('score', 0),
            'score_raw': r.get('score_raw'),
            'sources': r.get('sources', []),
            'agreement_bonus': r.get('agreement_bonus'),
            'components': r.get('components', {}),
            'sector': sectors_map.get(r.get('symbol'), 'Unknown'),
            'in_universe': r.get('symbol') in universe_set,
        }
        for r in top10
    ]

    # Candidates worth adding: above threshold & not in universe — full list
    candidates = sorted(
        [r for r in out_of_uni if r['score'] >= max(threshold, 3.0)],
        key=lambda r: r['score'], reverse=True,
    )

    return {
        'generated_at': latest.get('generated_at'),
        'threshold': threshold,
        'universe_size': len(universe),
        'top_10_composite': top10_rows,
        'in_universe_above_threshold': [r for r in in_uni if r['score'] >= threshold],
        'candidates_to_join': candidates,
        'candidates_count': len(candidates),
    }


def _ie_build_insights():
    """Compose 3-5 PenPen-says headline insights from current data."""
    out = []
    cand = _ie_build_candidates()
    alpaca = _ie_build_alpaca()
    fc = _read_json_safe(FORECASTER_DIR / 'latest.json', default={}) or {}
    tickers = fc.get('tickers', []) or []
    threshold = cand.get('threshold', 5.0)

    # 1. Top composite pick
    if tickers:
        top = tickers[0]
        srcs = top.get('sources', [])
        all_4 = len(srcs) >= 4
        in_uni = top.get('symbol') in {r['symbol'] for r in cand.get('in_universe_above_threshold', [])} \
            or top.get('symbol') in {x['symbol'] for x in cand.get('top_10_composite', []) if x.get('in_universe')}
        out.append(
            f"🧠 Composite likes {top['symbol']} most strongly today "
            f"({top['score']:.2f}, {len(srcs)} source{'s' if len(srcs)!=1 else ''} agreeing"
            f"{', all 4' if all_4 else ''}). "
            f"{'Already in universe. ✅' if in_uni else 'Not yet in wheel universe.'}"
        )

    # 2. Best candidate to add
    candidates = cand.get('candidates_to_join', [])
    if candidates:
        c0 = candidates[0]
        comps = c0.get('components') or {}
        comp_bits = ', '.join(f"{k.replace('_signal','')}: {v:.2f}" for k, v in sorted(comps.items(), key=lambda x: -x[1])[:2])
        out.append(
            f"🆕 {c0['symbol']} would be added to the universe tomorrow — "
            f"composite {c0['score']:.2f} ({comp_bits}). Not currently tradeable in wheel."
        )

    # 3. Sector concentration warning
    sec_map = (alpaca or {}).get('sector_market_value') or {}
    total_abs = sum(abs(v) for v in sec_map.values()) or 0
    if total_abs > 0:
        # Pick the largest sector by absolute exposure
        top_sec, top_val = max(sec_map.items(), key=lambda kv: abs(kv[1]))
        pct = abs(top_val) / total_abs * 100
        if pct >= 35:
            label = '⚠️' if pct < 50 else '🔴'
            out.append(
                f"{label} Sector concentration: {pct:.0f}% {top_sec}. "
                f"{'Approaching' if pct < 50 else 'Over'} 50% paper cap."
            )

    # 4. Lifetime P&L since starting capital
    sc = (alpaca or {}).get('starting_capital', WHEEL_STARTING_CAPITAL)
    tot = (alpaca or {}).get('total_pnl_dollars', 0) or 0
    tot_pct = (alpaca or {}).get('total_pnl_pct', 0) or 0
    money_s = f"-${abs(tot):,.2f}" if tot < 0 else f"+${tot:,.2f}"
    out.append(
        f"🏁 Started with ${sc:,.0f} on May 12. Currently {money_s} ({tot_pct:+.2f}%)."
    )

    # 5. Premium collected lifetime
    pg = (alpaca or {}).get('premium_collected_gross', 0) or 0
    pn = (alpaca or {}).get('premium_collected_net', 0) or 0
    if pg > 0:
        out.append(
            f"💰 Lifetime premium collected: ${pg:,.0f} gross, ${pn:,.0f} net."
        )

    # 6. Premium at risk
    at_risk = (alpaca or {}).get('open_premium_at_risk', 0) or 0
    if at_risk > 0:
        out.append(f"⏳ ${at_risk:,.0f} at risk in working CSPs.")

    # 7. YTD / MTD performance
    try:
        pnl_data = _ie_build_pnl()
        ytd = pnl_data.get('ytd', {})
        if ytd.get('trades', 0) > 0:
            yr = datetime.utcnow().strftime('%Y')
            wr = ytd.get('win_rate', 0)
            out.append(
                f"📊 {yr} YTD: +${ytd.get('realized', 0):,.2f} realized, "
                f"{ytd.get('wins', 0)} wins / {ytd.get('losses', 0)} losses, "
                f"{wr:.0f}% win rate."
            )
        mtd = pnl_data.get('mtd', {})
        if mtd.get('trades', 0) > 0:
            mo = datetime.utcnow().strftime('%B %Y')
            out.append(
                f"📅 {mo} MTD: +${mtd.get('realized', 0):,.2f} realized "
                f"across {mtd.get('trades', 0)} trades."
            )
    except Exception:
        pass

    # 8. Today's P&L flavor
    today = (alpaca or {}).get('today_pnl_dollars', 0) or 0
    if abs(today) >= 50:
        sign = '📈' if today > 0 else '📉'
        money_t = f"-${abs(today):,.2f}" if today < 0 else f"+${today:,.2f}"
        out.append(
            f"{sign} Today's P&L: {money_t} "
            f"({(alpaca or {}).get('today_pnl_pct', 0):+.2f}%)."
        )

    # 5. Signal that's quiet today
    quiet = []
    src_files = [
        ('🏛️ Politicians', POL_SIG_DIR / 'latest.json', 5.0),
        ('🐋 Top Trader', TOP_TRADER_DIR / 'latest.json', 8.0),
        ('📰 News', NEWS_SIG_DIR / 'latest.json', 5.0),
        ('🏦 Analysts', ANL_SIG_DIR / 'latest.json', 8.0),
    ]
    for label, path, thr in src_files:
        d = _read_json_safe(path, default={}) or {}
        above = sum(1 for t in (d.get('tickers') or []) if t.get('score', 0) >= thr)
        if above == 0:
            quiet.append(label)
    if quiet:
        out.append(f"😴 Quiet today: {', '.join(quiet)} (no names above threshold).")

    # 6. Working orders
    open_orders = (alpaca or {}).get('open_orders_count', 0)
    if open_orders > 0:
        out.append(f"🟡 {open_orders} working order{'s' if open_orders != 1 else ''} on the book.")

    # Fallback so banner never goes dark
    if not out:
        out.append("🐧 PenPen is watching. No fresh insights this minute.")

    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'insights': out,
    }


def _ie_build_composite():
    """Everything the dashboard needs, in one call (60s cache)."""
    wheel_summary = {}
    try:
        with app.test_request_context('/api/wheel/summary'):
            wheel_summary = json.loads(api_wheel_summary().get_data(as_text=True))
    except Exception as e:
        wheel_summary = {'error': str(e)}

    signal_health = {
        'politician': _signal_block(POL_SIG_DIR / 'latest.json', 5.0,
                                    'Politician', '🏛️'),
        'top_trader': _signal_block(TOP_TRADER_DIR / 'latest.json', 8.0,
                                    'Top Trader', '🐋'),
        'news': _signal_block(NEWS_SIG_DIR / 'latest.json', 5.0,
                              'News', '📰'),
        'analyst': _signal_block(ANL_SIG_DIR / 'latest.json', 8.0,
                                 'Analyst', '🏦'),
    }

    # Backtest verdicts per source
    backtests = {}
    for key, path in [
        ('politician', POL_SIG_DIR / 'backtest.json'),
        ('top_trader', TOP_TRADER_DIR / 'backtest.json'),
        ('news', NEWS_SIG_DIR / 'backtest.json'),
        ('analyst', ANL_SIG_DIR / 'backtest.json'),
        ('forecaster', FORECASTER_DIR / 'backtest.json'),
    ]:
        d = _read_json_safe(path, default={}) or {}
        if 'error' not in d:
            backtests[key] = {
                'generated_at': d.get('generated_at'),
                'verdict': d.get('verdict'),
                'excess_30d': (d.get('excess_return_vs_spy') or {}).get('30d'),
                'spy_return': d.get('spy_return'),
            }
        else:
            backtests[key] = {'verdict': 'no_data_yet'}

    forecaster = {}
    fc_latest = _read_json_safe(FORECASTER_DIR / 'latest.json', default={}) or {}
    forecaster = {
        'generated_at': fc_latest.get('generated_at'),
        'weights_used': fc_latest.get('weights_used', {}),
        'calibration': fc_latest.get('calibration', {}),
        'ticker_count': fc_latest.get('ticker_count', 0),
        'active_sources': fc_latest.get('active_sources', []),
        'blacklist_count': len(fc_latest.get('blacklist', []) or []),
    }

    # Recent activity timeline from trade journal (last 10)
    trades = _read_jsonl(WHEEL_DIR / 'trades.jsonl')
    activity = []
    for t in reversed(trades[-30:]):
        action = str(t.get('action', ''))
        emoji = ('📝' if action == 'simulated'
                 else '✅' if action == 'submitted'
                 else '🛑' if action.startswith('blocked') or action.startswith('submit_failed')
                 else '🔄')
        activity.append({
            'ts': t.get('ts') or t.get('timestamp'),
            'emoji': emoji,
            'action': action,
            'underlying': t.get('underlying'),
            'occ_symbol': t.get('occ_symbol'),
            'reason': (t.get('reason') or '')[:80],
        })
        if len(activity) >= 10:
            break

    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'wheel_summary': wheel_summary,
        'signal_health': signal_health,
        'backtests': backtests,
        'forecaster': forecaster,
        'candidates': _ie_build_candidates(),
        'alpaca': _ie_build_alpaca(),
        'insights': _ie_build_insights().get('insights', []),
        'activity': activity,
        'wheel_config': _ie_wheel_config_safe(),
        'pnl': _ie_build_pnl(),
        'ledger': _load_account_ledger(),
    }


def _ie_wheel_config_safe():
    cfg_file = WHEEL_SKILL / 'config.yaml'
    if not cfg_file.exists():
        return {}
    try:
        c = yaml.safe_load(cfg_file.read_text())
        return {
            'live_trading': c.get('live_trading'),
            'dry_run': c.get('dry_run'),
            'paper_overrides': c.get('paper_overrides'),
            'risk': c.get('risk'),
            'regime': c.get('regime'),
            'universe_size': len(c.get('universe', []) or []),
        }
    except Exception:
        return {}


def _ie_build_pnl():
    """Multi-period P&L breakdown for the dashboard."""
    pnl = _walk_wheel_trades_for_pnl()
    today = datetime.utcnow()
    cur_yr = today.strftime('%Y')
    cur_ym = today.strftime('%Y-%m')

    def _bucket_totals(by_dict, key=None):
        totals = {
            'realized': 0.0, 'premium_gross': 0.0, 'premium_net': 0.0,
            'spend': 0.0, 'wins': 0, 'losses': 0, 'trades': 0,
        }
        items = by_dict.items() if key is None else [
            (k, v) for k, v in by_dict.items() if k == key
        ]
        for _, v in items:
            for f in totals:
                totals[f] += v.get(f, 0)
        denom = totals['wins'] + totals['losses']
        totals['win_rate'] = (totals['wins'] / denom * 100) if denom else 0
        # Unrealized only meaningful for lifetime
        return totals

    by_month = pnl['by_month']
    by_year = pnl['by_year']

    lifetime = _bucket_totals(by_month)
    lifetime['unrealized'] = 0.0  # filled in by caller from Alpaca
    ytd = _bucket_totals(by_year, key=cur_yr)
    mtd = _bucket_totals(by_month, key=cur_ym)

    # Last 12 months bar series
    today_dt = today
    months = []
    for i in range(11, -1, -1):
        y = today_dt.year
        m = today_dt.month - i
        while m <= 0:
            m += 12
            y -= 1
        ym = f"{y:04d}-{m:02d}"
        b = by_month.get(ym) or {
            'realized': 0, 'premium_gross': 0, 'premium_net': 0,
            'spend': 0, 'wins': 0, 'losses': 0, 'trades': 0
        }
        months.append({
            'period': ym,
            'realized': b.get('realized', 0),
            'premium_gross': b.get('premium_gross', 0),
            'premium_net': b.get('premium_net', 0),
            'spend': b.get('spend', 0),
            'wins': b.get('wins', 0),
            'losses': b.get('losses', 0),
            'trades': b.get('trades', 0),
            'win_rate': (b.get('wins', 0) / (b.get('wins', 0) + b.get('losses', 0)) * 100)
                if (b.get('wins', 0) + b.get('losses', 0)) else 0,
        })

    # Years series
    years = []
    for yr in sorted(by_year.keys(), reverse=True):
        b = by_year[yr]
        denom = b.get('wins', 0) + b.get('losses', 0)
        years.append({
            'period': yr,
            'realized': b.get('realized', 0),
            'premium_gross': b.get('premium_gross', 0),
            'premium_net': b.get('premium_net', 0),
            'spend': b.get('spend', 0),
            'wins': b.get('wins', 0),
            'losses': b.get('losses', 0),
            'trades': b.get('trades', 0),
            'win_rate': (b.get('wins', 0) / denom * 100) if denom else 0,
        })

    # Per-account breakdown (single account today; structure ready for multi)
    led = _load_account_ledger()
    by_account = []
    for a in led.get('accounts', []):
        by_account.append({
            'account_id': a.get('id'),
            'type': a.get('type'),
            'starting_capital': a.get('starting_capital'),
            'started_at': a.get('started_at'),
            'ended_at': a.get('ended_at'),
            'lifetime_pnl': pnl['realized']
                if a.get('id') == led.get('active_account_id') else 0,
            'trades': sum(b.get('trades', 0) for b in by_month.values())
                if a.get('id') == led.get('active_account_id') else 0,
        })

    return {
        'generated_at': datetime.utcnow().isoformat() + 'Z',
        'active_account_id': led.get('active_account_id'),
        'lifetime': lifetime,
        'ytd': ytd,
        'mtd': mtd,
        'by_month': months,
        'by_year': years,
        'by_account': by_account,
        'closed_cycles': pnl['closed_cycles'],
        'open_legs_count': pnl['open_legs_count'],
    }


@app.route('/api/investor_engine/pnl')
def api_investor_engine_pnl():
    return jsonify(_ie_cache_get('pnl', 60, _ie_build_pnl))


@app.route('/api/investor_engine/ledger')
def api_investor_engine_ledger():
    return jsonify(_load_account_ledger())


@app.route('/api/investor_engine/tax_export/<year>')
def api_investor_engine_tax_export(year):
    """CSV of all closed cycles for a given tax year."""
    pnl = _walk_wheel_trades_for_pnl()
    rows = [c for c in pnl['closed_cycles'] if (c.get('close_date') or '').startswith(year)]
    headers = ['symbol', 'occ_symbol', 'open_date', 'close_date',
               'holding_period_days', 'premium_credit', 'close_debit',
               'realized_pnl', 'outcome']
    lines = [','.join(headers)]
    for r in rows:
        lines.append(','.join(str(r.get(h, '')) for h in headers))
    csv = '\n'.join(lines) + '\n'
    return Response(
        csv,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename="wheel_closed_{year}.csv"'},
    )


@app.route('/api/investor_engine/composite')
def api_investor_engine_composite():
    return jsonify(_ie_cache_get('composite', 60, _ie_build_composite))


@app.route('/api/investor_engine/alpaca')
def api_investor_engine_alpaca():
    return jsonify(_ie_cache_get('alpaca', 30, _ie_build_alpaca))


@app.route('/api/investor_engine/candidates')
def api_investor_engine_candidates():
    return jsonify(_ie_cache_get('candidates', 60, _ie_build_candidates))


@app.route('/api/investor_engine/insights')
def api_investor_engine_insights():
    return jsonify(_ie_cache_get('insights', 300, _ie_build_insights))


@app.route('/investor_engine')
def investor_engine_dashboard():
    dash = pathlib.Path(__file__).parent / 'investor_engine.html'
    if dash.exists():
        return dash.read_text()
    return '<h1>Investor Engine dashboard not yet built</h1>', 404


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=False)
