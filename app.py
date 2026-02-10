from flask import Flask, request, jsonify, render_template
import sqlite3
from datetime import datetime

app = Flask(__name__)

# --- 数据库初始化 ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    print("Opened database successfully")

    # --- 更新 records 表 ---
    columns = [col[1] for col in cursor.execute("PRAGMA table_info(records)").fetchall()]
    if 'category' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN category TEXT NOT NULL DEFAULT "general"')
    if 'date' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN date TEXT')
    if 'time' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN time TEXT')
    if 'urgency' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN urgency TEXT')
    if 'status' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN status TEXT NOT NULL DEFAULT "pending"')
    if 'quantity' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN quantity TEXT')
    if 'unit' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN unit TEXT')
    if 'brand' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN brand TEXT')
    # 为衣物清单添加新字段
    if 'person_id' not in columns:
        cursor.execute('ALTER TABLE records ADD COLUMN person_id INTEGER')
    if 'type' not in columns: # 衣物类型
        cursor.execute('ALTER TABLE records ADD COLUMN type TEXT')
    if 'color' not in columns: # 衣物颜色
        cursor.execute('ALTER TABLE records ADD COLUMN color TEXT')


    # 创建 records 表（如果不存在）
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            content TEXT, 
            category TEXT NOT NULL DEFAULT "general",
            date TEXT, time TEXT, urgency TEXT,
            status TEXT NOT NULL DEFAULT "pending",
            quantity TEXT, unit TEXT, brand TEXT,
            person_id INTEGER, type TEXT, color TEXT
        )
    ''')

    # --- 创建 people 表 ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE
        )
    ''')

    print("Table schemas are up to date.")
    conn.commit()
    conn.close()

init_db() # 启动时初始化数据库和表

# --- 人物 API ---
@app.route('/api/people', methods=['GET'])
def get_people():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM people ORDER BY name")
    people = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(people)

@app.route('/api/people', methods=['POST'])
def add_person():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({"error": "Name is required"}), 400
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO people (name) VALUES (?)", (name,))
        conn.commit()
    except sqlite3.IntegrityError:
        return jsonify({"error": "Person with this name already exists"}), 409
    finally:
        conn.close()
    return jsonify({"status": "success"}), 201

# --- 记录 API ---

# 路由1: 获取记录
@app.route('/api/records', methods=['GET'])
def get_records():
    category = request.args.get('category', 'general')
    
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if category == 'clothes':
        # 特殊处理衣物清单，按人物分组
        cursor.execute("SELECT p.id as person_id, p.name as person_name, r.id, r.content, r.type, r.color, r.quantity FROM records r JOIN people p ON r.person_id = p.id WHERE r.category = 'clothes' ORDER BY p.name, r.id")
        clothes_by_person = {}
        for row in cursor.fetchall():
            person_id = row['person_id']
            if person_id not in clothes_by_person:
                clothes_by_person[person_id] = {
                    "person_name": row['person_name'],
                    "items": []
                }
            clothes_by_person[person_id]['items'].append(dict(row))
        records = list(clothes_by_person.values())
    else:
        status = request.args.get('status', 'pending')
        cursor.execute("SELECT * FROM records WHERE category = ? AND status = ? ORDER BY id DESC", (category, status))
        records = [dict(row) for row in cursor.fetchall()]
        
    conn.close()
    return jsonify(records)

# 路由2: 添加一条新记录
@app.route('/api/records', methods=['POST'])
def add_record():
    record_data = request.get_json()
    category = record_data.get('category', 'general')
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()

    if category == 'clothes':
        # 添加衣物记录
        cursor.execute(
            "INSERT INTO records (content, category, person_id, type, color, quantity) VALUES (?, ?, ?, ?, ?, ?)",
            (record_data['content'], 'clothes', record_data['person_id'], record_data['type'], record_data['color'], record_data['quantity'])
        )
    else:
        # 添加其他记录
        cursor.execute(
            "INSERT INTO records (content, category, date, time, urgency, status, quantity, unit, brand) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (record_data['content'], category, record_data.get('date'), record_data.get('time'), record_data.get('urgency'), 'pending', record_data.get('quantity'), record_data.get('unit'), record_data.get('brand'))
        )
    
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# 新增路由: 更新记录状态
@app.route('/api/records/<int:record_id>/status', methods=['PUT'])
def update_record_status(record_id):
    status_data = request.get_json()
    new_status = status_data.get('status')

    if not new_status:
        return jsonify({"error": "New status is required"})
    if new_status not in ['pending', 'completed', 'cancelled']:
        return jsonify({"error": "Invalid status"})
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE records SET status = ? WHERE id = ?", (new_status, record_id))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# 新增路由: 清空购物清单
@app.route('/api/shopping/clear', methods=['POST'])
def clear_shopping_list():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE category = 'shopping'")
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})


# 路由3: 删除一条记录
@app.route('/api/records/<int:record_id>', methods=['DELETE'])
def delete_record(record_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM records WHERE id = ?", (record_id,))
    conn.commit()
    conn.close()
    return jsonify({"status": "success"})

# --- 页面服务 ---
# 路由4: 渲染前端HTML页面
@app.route('/')
def index():
    return render_template('index.html')

# 新增页面路由
@app.route('/<page_name>')
def show_page(page_name):
    # 动态渲染页面，避免为每个页面都写一个路由
    if page_name in ['medicine', 'clothes', 'shopping']:
        return render_template(f'{page_name}.html')
    return "Page not found", 404


if __name__ == '__main__':
    app.run(debug=True) # 启动服务器