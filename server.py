from flask import Flask, send_from_directory, request, jsonify, Response, send_file
import json, os, subprocess, yaml
from datetime import datetime

app = Flask(__name__, static_folder='.')

# Paths
BASE_DIR = '/Users/scottanderson/.openclaw/workspace'
MC_DIR = '/Users/scottanderson/.openclaw/workspace/mission_control'
TASKS_FILE = f'{MC_DIR}/tasks.json'
DIST_LISTS_FILE = f'{BASE_DIR}/distribution_lists.json'
TOKEN_STATS_FILE = f'{MC_DIR}/token_stats.json'
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
    stats.setdefault('sessions', []).append(data)
    stats['last_updated'] = datetime.now().isoformat()
    # Compute per-model totals
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
    # Update grand totals
    stats['cost_usd'] = sum(t['total_cost_usd'] for t in totals.values())
    stats['tokens_in'] = sum(t['tokens_in'] for t in totals.values())
    stats['tokens_out'] = sum(t['tokens_out'] for t in totals.values())
    stats['cache_hit_tokens'] = sum(t['cache_hit_tokens'] for t in totals.values())
    save_json_file(TOKEN_STATS_FILE, stats)
    return jsonify({"status": "success"})

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

# ─── Start ───────────────────────────────────────────────────────────────────

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8888, debug=False)
