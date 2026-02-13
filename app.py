from flask import Flask, request, jsonify, render_template, redirect, url_for, send_from_directory
import sqlite3
import os # <--- 1. 确保导入 os 模块
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from user import User

app = Flask(__name__)
# 请务必在生产环境中更改此密钥
app.secret_key = 'a_very_secret_and_secure_key_for_flask_session'

# --- Flask-Login 初始化 ---
login_manager = LoginManager()
login_manager.init_app(app)
# 如果用户未登录并尝试访问受保护的页面，将他们重定向到'login'视图
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)

# --- 数据库初始化 (已重构以支持多用户) ---
def init_db():
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    print("Opened database successfully")

    # --- 创建 users 表 (如果不存在) ---
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            avatar TEXT
        )
    ''')

    # --- 创建 people 表 (如果不存在) ---
    # 这样修改后，它将不再删除现有数据
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS people (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id),
            UNIQUE(user_id, name)
        )
    ''')

    # --- 检查并更新 records 表，添加 user_id ---
    records_cols = [col[1] for col in cursor.execute("PRAGMA table_info(records)").fetchall()]
    if 'user_id' not in records_cols:
        cursor.execute('ALTER TABLE records ADD COLUMN user_id INTEGER')

    # --- 确保所有字段都存在 (用于旧数据库的迁移) ---
    columns = [col[1] for col in cursor.execute("PRAGMA table_info(records)").fetchall()]
    fields_to_add = {
        'category': 'TEXT NOT NULL DEFAULT "general"', 'date': 'TEXT', 'time': 'TEXT', 'urgency': 'TEXT',
        'status': 'TEXT NOT NULL DEFAULT "pending"', 'quantity': 'TEXT', 'unit': 'TEXT', 'brand': 'TEXT',
        'person_id': 'INTEGER', 'type': 'TEXT', 'color': 'TEXT', 'frequency': 'TEXT', 'style': 'TEXT',
        'needs_purchase': 'INTEGER DEFAULT 0', 'dosage': 'TEXT', 'total_quantity': 'INTEGER',
        'start_date': 'TEXT', 'refill_quantity': 'INTEGER', 'reminder_threshold': 'INTEGER',
        'source_record_id': 'INTEGER', 'shopping_source_id': 'INTEGER',
        'completion_notes': 'TEXT',
        'completion_photos': 'TEXT'
    }
    for field, definition in fields_to_add.items():
        if field not in columns:
            cursor.execute(f'ALTER TABLE records ADD COLUMN {field} {definition}')

    # --- 创建 records 表 (如果不存在) ---
    # 确保 records 表的定义是最新的
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            user_id INTEGER, content TEXT, category TEXT NOT NULL DEFAULT "general",
            date TEXT, time TEXT, urgency TEXT, status TEXT NOT NULL DEFAULT "pending",
            quantity TEXT, unit TEXT, brand TEXT, person_id INTEGER, type TEXT, color TEXT,
            frequency TEXT, style TEXT, needs_purchase INTEGER DEFAULT 0, dosage TEXT,
            total_quantity INTEGER, start_date TEXT, refill_quantity INTEGER,
            reminder_threshold INTEGER, source_record_id INTEGER, shopping_source_id INTEGER,
            completion_notes TEXT, completion_photos TEXT,
            FOREIGN KEY(user_id) REFERENCES users(id),
            FOREIGN KEY(person_id) REFERENCES people(id)
        )
    ''')

    print("Table schemas are up to date.")
    conn.commit()
    conn.close()

init_db()

# --- 用户认证 API 和页面 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')
        conn = None # 初始化
        try:
            conn = sqlite3.connect('database.db', timeout=15)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
            user_row = cursor.fetchone()

            if user_row and check_password_hash(user_row['password_hash'], password):
                user_obj = User(id=user_row['id'], username=user_row['username'], avatar=user_row['avatar'])
                login_user(user_obj, remember=True)
                return jsonify({"status": "success"})
            
            return jsonify({"error": "无效的用户名或密码"}), 401
        finally:
            if conn:
                conn.close()
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username')
        password = data.get('password')

        if not username or not password:
            return jsonify({"error": "用户名和密码不能为空"}), 400

        password_hash = generate_password_hash(password)
        conn = None
        try:
            conn = sqlite3.connect('database.db', timeout=15)
            cursor = conn.cursor()
            cursor.execute("INSERT INTO users (username, password_hash) VALUES (?, ?)", (username, password_hash))
            conn.commit()
            return jsonify({"status": "success"}), 201
        except sqlite3.IntegrityError:
            conn.rollback()
            return jsonify({"error": "用户名已存在"}), 409
        except sqlite3.Error as e:
            if conn: conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            if conn:
                conn.close()
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/api/user/current')
@login_required
def get_current_user_info():
    return jsonify({
        "username": current_user.username,
        "avatar": current_user.avatar,
        "id": current_user.id
    })

# --- 新增：处理头像上传的 API ---
@app.route('/api/user/avatar', methods=['POST'])
@login_required
def upload_avatar():
    if 'avatar' not in request.files:
        return jsonify({"error": "没有文件部分"}), 400
    
    file = request.files['avatar']
    if file.filename == '':
        return jsonify({"error": "没有选择文件"}), 400

    if file:
        # 确保 uploads 目录存在
        upload_folder = 'uploads'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)

        # 为了安全，生成一个唯一的文件名
        import uuid
        filename = str(uuid.uuid4()) + os.path.splitext(file.filename)[1]
        filepath = os.path.join(upload_folder, filename)
        file.save(filepath)

        # **关键修复**: 将路径转换为 URL 格式 (使用正斜杠)
        url_path = filepath.replace('\\', '/')

        # 更新数据库中的头像路径
        conn = _get_db_conn()
        cursor = conn.cursor()
        try:
            # **关键修复**: 保存 URL 格式的路径
            cursor.execute("UPDATE users SET avatar = ? WHERE id = ?", (url_path, current_user.id))
            conn.commit()
        except sqlite3.Error as e:
            conn.rollback()
            return jsonify({"error": str(e)}), 500
        finally:
            conn.close()
        
        # 返回新的头像路径，以便前端更新
        return jsonify({"status": "success", "avatar_url": f"/{url_path}"})

    return jsonify({"error": "文件上传失败"}), 500


# --- 新增：注销账户 API ---
@app.route('/api/user/delete', methods=['DELETE'])
@login_required
def delete_account():
    user_id = current_user.id
    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 1. 查找该用户上传的所有文件以便后续删除
        photo_paths_to_delete = []
        # 查找头像
        cursor.execute("SELECT avatar FROM users WHERE id = ?", (user_id,))
        avatar_row = cursor.fetchone()
        if avatar_row and avatar_row['avatar']:
            photo_paths_to_delete.append(avatar_row['avatar'])
        
        # 查找记录中的照片
        cursor.execute("SELECT completion_photos FROM records WHERE user_id = ? AND completion_photos IS NOT NULL", (user_id,))
        import json
        for row in cursor.fetchall():
            try:
                paths = json.loads(row['completion_photos'])
                if isinstance(paths, list):
                    photo_paths_to_delete.extend(paths)
            except json.JSONDecodeError:
                continue

        # 2. 从数据库中删除所有与用户相关的数据
        # 由于外键约束，删除顺序很重要：先删子表，再删主表
        cursor.execute("DELETE FROM records WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM people WHERE user_id = ?", (user_id,))
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
        
        conn.commit()

        # 3. 从文件系统中删除用户上传的文件
        for path in photo_paths_to_delete:
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError as e:
                    # 记录错误，但继续执行，以防文件被占用等问题
                    print(f"Error deleting file {path}: {e}")
        
        # 4. 登出用户
        logout_user()

    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
        
    return jsonify({"status": "success", "message": "账户已成功注销"})


# **新增**: 获取已完成的记录
@app.route('/api/records/completed', methods=['GET'])
@login_required
def get_completed_records():
    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    # 查询所有非药品提醒的、已完成的记录，按日期降序
    cursor.execute("""
        SELECT id, content, date, completion_notes, completion_photos 
        FROM records 
        WHERE user_id = ? AND status = 'completed' AND category != 'medicine_reminder'
        ORDER BY date DESC
    """, (user_id,))
    completed_records = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(completed_records)

# **新增**: 更新已完成记录的感想和照片
@app.route('/api/completed_records/<int:record_id>/details', methods=['POST'])
@login_required
def update_completed_details(record_id):
    notes = request.form.get('notes')
    photos = request.files.getlist('photos')
    
    photo_paths = []
    if photos:
        upload_folder = 'uploads'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        
        import uuid
        from werkzeug.utils import secure_filename

        for photo in photos:
            if photo and photo.filename != '':
                # 使用 secure_filename 和 uuid 确保文件名安全且唯一
                base_filename = secure_filename(photo.filename)
                unique_filename = str(uuid.uuid4()) + os.path.splitext(base_filename)[1]
                filepath = os.path.join(upload_folder, unique_filename)
                
                # **关键修复**: 保存文件到服务器
                photo.save(filepath)
                
                # **关键修复**: 存储 URL 格式的相对路径 (使用正斜杠)
                url_path = filepath.replace('\\', '/')
                photo_paths.append(url_path)

    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        cursor.execute("SELECT completion_photos FROM records WHERE id = ? AND user_id = ? AND status = 'completed'", (record_id, user_id))
        record = cursor.fetchone()
        if not record:
            return jsonify({"error": "记录不存在或权限不足"}), 404
        
        import json
        # 获取已有的照片列表
        existing_photos = json.loads(record['completion_photos']) if record['completion_photos'] else []
        
        # 将新上传的照片路径追加到列表中
        all_photos = existing_photos + photo_paths
        
        # 更新感想和照片列表
        cursor.execute("UPDATE records SET completion_notes = ?, completion_photos = ? WHERE id = ?", (notes, json.dumps(all_photos), record_id))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})


# --- 人物 API (已添加用户隔离) ---
@app.route('/api/people', methods=['GET'])
@login_required
def get_people():
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM people WHERE user_id = ? ORDER BY name", (current_user.id,))
    people = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return jsonify(people)

@app.route('/api/people', methods=['POST'])
@login_required
def add_person():
    data = request.get_json()
    name = data.get('name')
    if not name:
        return jsonify({"error": "Name is required"}), 400
    
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        # 修复：在插入前，先检查该用户是否已有同名人物
        cursor.execute("SELECT id FROM people WHERE name = ? AND user_id = ?", (name, user_id))
        if cursor.fetchone():
            return jsonify({"error": f"名称为 '{name}' 的人物已存在于您的账号中"}), 409

        # 如果不存在，则插入
        cursor.execute("INSERT INTO people (name, user_id) VALUES (?, ?)", (name, user_id))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        # 捕获其他可能的数据库错误
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"}), 201

@app.route('/api/people/<int:person_id>', methods=['DELETE'])
@login_required
def delete_person(person_id):
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        cursor.execute("SELECT id FROM people WHERE id = ? AND user_id = ?", (person_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "权限不足或人物不存在"}), 403

        cursor.execute("DELETE FROM records WHERE person_id = ? AND user_id = ?", (person_id, user_id))
        cursor.execute("DELETE FROM people WHERE id = ? AND user_id = ?", (person_id, user_id))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})

@app.route('/api/people/<int:person_id>/details', methods=['GET'])
@login_required
def get_person_details(person_id):
    conn = sqlite3.connect('database.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    user_id = current_user.id

    cursor.execute("SELECT id FROM people WHERE id = ? AND user_id = ?", (person_id, user_id))
    if not cursor.fetchone():
        return jsonify({"error": "权限不足或人物不存在"}), 403

    cursor.execute("SELECT * FROM records WHERE person_id = ? AND category = 'clothes' AND user_id = ?", (person_id, user_id))
    clothes = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT * FROM records WHERE person_id = ? AND category = 'medicine' AND user_id = ?", (person_id, user_id))
    medicines = [dict(row) for row in cursor.fetchall()]

    conn.close()
    return jsonify({"clothes": clothes, "medicines": medicines})

# --- 记录 API (已添加用户隔离) ---
@app.route('/api/records', methods=['GET'])
@login_required
def get_records():
    category = request.args.get('category', 'general')
    conn = None
    try:
        conn = sqlite3.connect('database.db', timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        user_id = current_user.id
        records = []

        if category == 'medicine':
            # --- 关键重构：将读和写分离 ---
            # 步骤1: 读取所有药品
            cursor.execute("SELECT * FROM records WHERE category = 'medicine' AND user_id = ?", (user_id,))
            medicines_to_update = cursor.fetchall()
            today = datetime.now().date()
            updates_to_perform = []

            for med in medicines_to_update:
                if med['start_date'] and med['total_quantity'] is not None and med['frequency'] and med['dosage']:
                    try:
                        start_date = datetime.strptime(med['start_date'], '%Y-%m-%d').date()
                        # 确保频率和用量是数字
                        frequency = int(med['frequency'])
                        dosage = int(med['dosage'])

                        if start_date < today:
                            days_passed = (today - start_date).days
                            total_consumption = days_passed * frequency * dosage
                            new_quantity = med['total_quantity'] - total_consumption
                            if new_quantity < 0:
                                new_quantity = 0
                            # 收集需要执行的更新，而不是立即执行
                            updates_to_perform.append((new_quantity, today.strftime('%Y-%m-%d'), med['id']))
                    except (ValueError, TypeError):
                        # 如果 frequency 或 dosage 不是有效数字，或者日期格式错误，则安全地跳过
                        print(f"Skipping update for medicine ID {med['id']} due to invalid data.")
                        continue
            
            # 步骤2: 一次性执行所有更新
            if updates_to_perform:
                cursor.executemany("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", updates_to_perform)
                conn.commit()

            # 步骤3: 重新查询以获取最新数据
            query = "SELECT p.id as person_id, p.name as person_name, r.* FROM records r JOIN people p ON r.person_id = p.id WHERE r.category = ? AND r.user_id = ? ORDER BY p.name, r.id"
            cursor.execute(query, (category, user_id))
            items_by_person = {}
            for row_obj in cursor.fetchall():
                row = dict(row_obj)
                person_id = row['person_id']
                if person_id not in items_by_person:
                    items_by_person[person_id] = {"person_id": person_id, "person_name": row['person_name'], "items": []}
                items_by_person[person_id]['items'].append(row)
            records = list(items_by_person.values())
        
        elif category in ['clothes']: # **修改**: 将 clothes 也移到这里
            query = "SELECT p.id as person_id, p.name as person_name, r.* FROM records r JOIN people p ON r.person_id = p.id WHERE r.category = ? AND r.user_id = ? ORDER BY p.name, r.id"
            cursor.execute(query, (category, user_id))
            items_by_person = {}
            for row_obj in cursor.fetchall():
                row = dict(row_obj)
                person_id = row['person_id']
                if person_id not in items_by_person:
                    items_by_person[person_id] = {"person_id": person_id, "person_name": row['person_name'], "items": []}
                items_by_person[person_id]['items'].append(row)
            records = list(items_by_person.values())
        
        else: # category == 'general' or 'shopping'
            # **关键修复**: 只有在 category 是 'general' 时才执行提醒逻辑
            if category == 'general':
                # --- 步骤 1: 执行药品自动消耗计算 (从 medicine 分支复制过来) ---
                cursor.execute("SELECT * FROM records WHERE category = 'medicine' AND user_id = ?", (user_id,))
                medicines_to_update = cursor.fetchall()
                today = datetime.now().date()
                updates_to_perform = []

                for med in medicines_to_update:
                    if med['start_date'] and med['total_quantity'] is not None and med['frequency'] and med['dosage']:
                        try:
                            start_date = datetime.strptime(med['start_date'], '%Y-%m-%d').date()
                            if start_date < today:
                                days_passed = (today - start_date).days
                                total_consumption = days_passed * int(med['frequency']) * int(med['dosage'])
                                new_quantity = med['total_quantity'] - total_consumption
                                if new_quantity < 0: new_quantity = 0
                                updates_to_perform.append((new_quantity, today.strftime('%Y-%m-%d'), med['id']))
                        except (ValueError, TypeError):
                            continue
                
                if updates_to_perform:
                    cursor.executemany("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", updates_to_perform)
                    conn.commit()
                
                # --- 步骤 2: 在更新后的数据基础上生成提醒 ---
                reminders = []
                today_str = datetime.now().strftime('%Y-%m-%d')
                
                # 1. 生成药品库存警告
                cursor.execute("""
                    SELECT r.id, p.name, r.content, r.total_quantity, r.reminder_threshold 
                    FROM records r 
                    LEFT JOIN people p ON r.person_id = p.id 
                    WHERE r.category = 'medicine' AND r.user_id = ?
                """, (user_id,))
                for med_row_obj in cursor.fetchall():
                    med_row = dict(med_row_obj)
                    try:
                        total_quantity = int(med_row['total_quantity'])
                        reminder_threshold = int(med_row['reminder_threshold'])
                        if total_quantity < reminder_threshold:
                            person_name = med_row['name'] or '未知人物'
                            reminder_content = f"库存警告: {person_name}的'{med_row['content']}'数量不足"
                            # **关键修复**: 添加 original_medicine_id 字段
                            reminders.append({
                                "id": f"med_{med_row['id']}", 
                                "content": reminder_content, 
                                "category": "general", 
                                "date": today_str, 
                                "time": "08:00", 
                                "urgency": "高", 
                                "status": "pending", 
                                "is_dynamic_reminder": True,
                                "original_medicine_id": med_row['id'] # <-- 新增的这行是关键
                            })
                    except (ValueError, TypeError, KeyError):
                        continue

                # 2. **新增**: 生成购物提醒
                cursor.execute("SELECT DISTINCT date FROM records WHERE category = 'shopping' AND status = 'pending' AND date IS NOT NULL AND user_id = ?", (user_id,))
                shopping_dates = [row['date'] for row in cursor.fetchall()]
                for s_date in shopping_dates:
                    # **关键修复**: 使用一个不会与数据库ID冲突的、唯一的字符串ID
                    # 并且明确标识这是一个购物提醒
                    reminder_id = f"dynamic_shopping_{s_date}"
                    reminders.append({
                        "id": reminder_id, 
                        "content": f"有计划的购物任务 ({s_date})", 
                        "category": "general", 
                        "date": s_date, 
                        "time": "09:00", 
                        "urgency": "中", 
                        "status": "pending", 
                        "is_dynamic_reminder": True,
                        "is_shopping_reminder": True # **新增**: 添加一个明确的标识
                    })

                # 3. 获取普通的通用记录
                sort_by = request.args.get('sort_by', 'urgency')
                order_clause = "ORDER BY date ASC, "
                if sort_by == 'time':
                    order_clause += "time ASC, CASE urgency WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 ELSE 4 END"
                else:
                    order_clause += "CASE urgency WHEN '高' THEN 1 WHEN '中' THEN 2 WHEN '低' THEN 3 ELSE 4 END, time ASC"

                query = f"SELECT * FROM records WHERE category = ? AND status = 'pending' AND user_id = ? {order_clause}"
                cursor.execute(query, (category, user_id))
                general_records = [dict(row) for row in cursor.fetchall()]
                
                # 4. 合并并返回
                records = reminders + general_records
            
            # **关键修复**: 为 shopping category 添加独立的、正确的处理逻辑
            elif category == 'shopping':
                status = request.args.get('status')
                if status:
                    query = "SELECT * FROM records WHERE category = ? AND status = ? AND user_id = ? ORDER BY date DESC, id DESC"
                    cursor.execute(query, (category, status, user_id))
                else: # 如果没有提供 status，则获取所有购物项
                    query = "SELECT * FROM records WHERE category = ? AND user_id = ? ORDER BY date DESC, id DESC"
                    cursor.execute(query, (category, user_id))
                records = [dict(row) for row in cursor.fetchall()]
            
        return jsonify(records)
    except Exception as e:
        # 添加一个顶层异常捕获，以便调试
        print(f"An unexpected error occurred in get_records: {e}")
        return jsonify({"error": "服务器内部错误"}), 500
    finally:
        if conn:
            conn.close()

@app.route('/api/records', methods=['POST'])
@login_required
def add_record():
    data = request.get_json()
    category = data.get('category', 'general')
    user_id = current_user.id
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    try:
        person_id = data.get('person_id')
        if person_id:
            # **关键修复**: 验证 person_id 是否属于当前用户
            cursor.execute("SELECT id FROM people WHERE id = ? AND user_id = ?", (person_id, user_id))
            if not cursor.fetchone():
                return jsonify({"error": "无效的人物ID"}), 403

        if category == 'clothes':
            cursor.execute("INSERT INTO records (user_id, content, category, person_id, type, color, quantity) VALUES (?, ?, ?, ?, ?, ?, ?)", (user_id, data['content'], 'clothes', person_id, data['type'], data['color'], data['quantity']))
        elif category == 'medicine':
            # **关键修复**: 为 reminder_threshold 设置默认值
            reminder_threshold = data.get('reminder_threshold')
            if not reminder_threshold:
                reminder_threshold = 5 # 设置默认值为 5

            cursor.execute("INSERT INTO records (user_id, content, category, person_id, frequency, dosage, style, color, total_quantity, start_date, refill_quantity, reminder_threshold) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                           (user_id, data['content'], 'medicine', person_id, data.get('frequency'), data.get('dosage'), data['style'], data['color'], data.get('total_quantity'), data.get('start_date'), data.get('refill_quantity'), reminder_threshold))
        elif category == 'shopping':
            cursor.execute("INSERT INTO records (user_id, content, category, date, quantity, unit, brand) VALUES (?, ?, 'shopping', ?, ?, ?, ?)", (user_id, data['content'], data.get('date'), data.get('quantity'), data.get('unit'), data.get('brand')))
        else:
            cursor.execute("INSERT INTO records (user_id, content, category, date, time, urgency, status) VALUES (?, ?, ?, ?, ?, ?, 'pending')", (user_id, data['content'], category, data.get('date'), data.get('time'), data.get('urgency')))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"}), 201

@app.route('/api/records/<int:record_id>', methods=['PUT'])
@login_required
def update_record(record_id):
    data = request.get_json()
    category = data.get('category', 'general')
    user_id = current_user.id
    conn = sqlite3.connect('database.db')
    cursor = conn.cursor()
    try:
        cursor.execute("SELECT id FROM records WHERE id = ? AND user_id = ?", (record_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "权限不足或记录不存在"}), 403
        
        if category == 'general':
            cursor.execute("UPDATE records SET content=?, date=?, time=?, urgency=? WHERE id=?", (data['content'], data['date'], data['time'], data['urgency'], record_id))
        elif category == 'shopping':
            cursor.execute("UPDATE records SET content=?, date=?, quantity=?, unit=?, brand=? WHERE id=?", (data['content'], data.get('date'), data.get('quantity'), data.get('unit'), data.get('brand'), record_id))
        elif category == 'clothes':
            cursor.execute("UPDATE records SET person_id=?, content=?, type=?, color=?, quantity=? WHERE id=?", (data['person_id'], data['content'], data['type'], data['color'], data['quantity'], record_id))
        elif category == 'medicine':
            # **关键修复**: 为 reminder_threshold 设置默认值
            reminder_threshold = data.get('reminder_threshold')
            if not reminder_threshold:
                reminder_threshold = 5 # 设置默认值为 5

            cursor.execute("UPDATE records SET person_id=?, content=?, frequency=?, dosage=?, style=?, color=?, refill_quantity=?, reminder_threshold=? WHERE id=?", 
                           (data['person_id'], data['content'], data.get('frequency'), data.get('dosage'), data['style'], data['color'], data.get('refill_quantity'), reminder_threshold, record_id))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})

@app.route('/api/records/<int:record_id>', methods=['DELETE'])
@login_required
def delete_record(record_id):
    conn = None
    try:
        conn = sqlite3.connect('database.db', timeout=15)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        user_id = current_user.id
        
        cursor.execute("SELECT category, source_record_id FROM records WHERE id = ? AND user_id = ?", (record_id, user_id))
        record = cursor.fetchone()
        if not record:
            return jsonify({"error": "记录不存在或权限不足"}), 404
        
        # **关键修复**: 恢复并增强删除逻辑
        # 如果删除的是一个购物清单项，且它来自一个药品
        if record['category'] == 'shopping' and record['source_record_id']:
            # 将源药品的 needs_purchase 状态重置为 0
            cursor.execute("UPDATE records SET needs_purchase = 0 WHERE id = ? AND user_id = ?", (record['source_record_id'], user_id))
        
        # 如果删除的是一条药品记录
        if record['category'] == 'medicine':
            # 同时删除由它生成的、还存在于购物清单中的待购项
            cursor.execute("DELETE FROM records WHERE category = 'shopping' AND source_record_id = ? AND user_id = ?", (record_id, user_id))

        # **关键修改**: 移除 shopping_source_id 相关逻辑
        
        # 最后，删除记录本身
        cursor.execute("DELETE FROM records WHERE id = ? AND user_id = ?", (record_id, user_id))
        conn.commit()
    except sqlite3.Error as e:
        if conn: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
    return jsonify({"status": "success"})

@app.route('/api/records/<int:record_id>/status', methods=['PUT'])
@login_required
def update_record_status(record_id):
    data = request.get_json()
    new_status = data.get('status')
    if not new_status in ['completed', 'pending']:
        return jsonify({"error": "无效的状态"}), 400

    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        # 1. 获取记录信息，并严格检查其类型
        cursor.execute("SELECT category, source_record_id FROM records WHERE id = ? AND user_id = ?", (record_id, user_id))
        record = cursor.fetchone()
        if not record:
            return jsonify({"error": "记录不存在或权限不足"}), 404

        # **关键修复**: 如果是通用记录，只更新状态，然后立即返回
        if record['category'] == 'general':
            cursor.execute("UPDATE records SET status = ? WHERE id = ?", (new_status, record_id))
            conn.commit()
            return jsonify({"status": "success", "message": "通用记录状态已更新"})

        # --- 从这里开始，代码只处理 shopping 类型的记录 ---
        if record['category'] != 'shopping':
            return jsonify({"error": "此接口只用于更新购物清单项的状态"}), 400

        source_medicine_id = record['source_record_id']

        # 2. 如果购物项来自药品，执行核心联动逻辑
        if source_medicine_id:
            # 获取源药品的当前数量和预设的补充数量
            cursor.execute("SELECT total_quantity, refill_quantity FROM records WHERE id = ? AND user_id = ?", (source_medicine_id, user_id))
            medicine = cursor.fetchone()
            if not medicine:
                # 如果源药品被删除了，安全地继续，只更新购物项状态
                pass
            else:
                refill_amount = medicine['refill_quantity']
                if not refill_amount or refill_amount <= 0:
                    refill_amount = 0 # 即使未设置，也继续执行

                current_total = medicine['total_quantity'] or 0
                new_total = current_total

                # 根据新的状态，增加或扣除药品数量
                if new_status == 'completed':
                    new_total += refill_amount
                    cursor.execute("UPDATE records SET needs_purchase = 0 WHERE id = ?", (source_medicine_id,))
                elif new_status == 'pending':
                    new_total -= refill_amount
                    if new_total < 0: new_total = 0
                    cursor.execute("UPDATE records SET needs_purchase = 1 WHERE id = ?", (source_medicine_id,))
                
                new_start_date = datetime.now().strftime('%Y-%m-%d')
                cursor.execute("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", (new_total, new_start_date, source_medicine_id))

        # 3. 更新购物项本身的状态
        cursor.execute("UPDATE records SET status = ? WHERE id = ?", (new_status, record_id))

        # 4. **关键修改**: 移除 shopping_source_id 相关逻辑

        conn.commit()
    except (sqlite3.Error, ValueError) as e:
        if conn: conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if conn:
            conn.close()
    return jsonify({"status": "success"})

# --- 特定功能 API (已添加用户隔离) ---

def _get_db_conn():
    conn = sqlite3.connect('database.db', timeout=15) # 确保这里有 timeout
    conn.row_factory = sqlite3.Row
    return conn



# **关键修改**: 再次审查并加固此函数
@app.route('/api/records/<int:record_id>/refill', methods=['POST'])
@login_required
def refill_medicine_from_purchase(record_id):
    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        # 1. 验证药品所有权
        cursor.execute("SELECT total_quantity, refill_quantity FROM records WHERE id = ? AND user_id = ? AND category = 'medicine'", (record_id, user_id))
        record = cursor.fetchone()
        if not record:
            return jsonify({"error": "药品不存在或权限不足"}), 404
        
        # 2. 计算补充数量，即使未设置也继续执行
        refill_amount = record['refill_quantity']
        if not refill_amount or refill_amount <= 0:
            refill_amount = 0 # 如果未设置，则不增加库存，但后续操作继续

        # 3. 增加库存
        new_total = (record['total_quantity'] or 0) + refill_amount
        new_start_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", (new_total, new_start_date, record_id))

        # 4. 将药品的“需要购买”状态取消
        cursor.execute("UPDATE records SET needs_purchase = 0 WHERE id = ?", (record_id,))

        # 5. **联动核心**: 在购物清单中查找对应的项，并将其状态更新为 'completed'
        # 无论是否找到，这个操作都是安全的
        cursor.execute("UPDATE records SET status = 'completed' WHERE category = 'shopping' AND source_record_id = ? AND user_id = ?", (record_id, user_id))

        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        print(f"Error in refill_medicine_from_purchase: {e}") # 增加日志打印
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success", "message": "药品已补充，购物清单已更新"})


def auto_refill_medicine(record_id, user_id):
    """内部函数，用于补充药品，需要被调用时提供用户上下文"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 验证药品所有权
        cursor.execute("SELECT total_quantity, refill_quantity FROM records WHERE id = ? AND user_id = ?", (record_id, user_id))
        record = cursor.fetchone()
        if not record or not record['refill_quantity']:
            raise ValueError("Refill quantity not set or permission denied")

        new_total = (record['total_quantity'] or 0) + record['refill_quantity']
        new_start_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", (new_total, new_start_date, record_id))
        conn.commit()
    finally:
        conn.close()

@app.route('/api/records/<int:record_id>/purchase', methods=['PUT'])
@login_required
def toggle_medicine_purchase(record_id):
    data = request.get_json()
    needs_purchase = data.get('needs_purchase', False)
    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        cursor.execute("SELECT id, person_id FROM records WHERE id = ? AND category = 'medicine' AND user_id = ?", (record_id, user_id))
        medicine_record = cursor.fetchone()
        if not medicine_record:
            return jsonify({"error": "药品不存在或权限不足"}), 404

        cursor.execute("UPDATE records SET needs_purchase = ? WHERE id = ?", (1 if needs_purchase else 0, record_id))
        
        if needs_purchase:
            # **关键修复**: 使用 LEFT JOIN，并只查询需要的字段
            cursor.execute("""
                SELECT r.content, p.name 
                FROM records r 
                LEFT JOIN people p ON r.person_id = p.id 
                WHERE r.id = ?
            """, (record_id,))
            medicine_info = cursor.fetchone()

            # **关键修复**: 即使 medicine_info 存在，也要处理 p.name 可能为 NULL 的情况
            if medicine_info:
                person_name = medicine_info['name'] or '未指定人物'
                shopping_content = f"药品: {person_name} - {medicine_info['content']}"
                
                # **关键修复**: 检查是否已存在，如果不存在则插入
                cursor.execute("SELECT id FROM records WHERE category = 'shopping' AND source_record_id = ? AND user_id = ?", (record_id, user_id))
                if not cursor.fetchone():
                    # **关键修复**: 插入时包含 date
                    record_date = datetime.now().strftime('%Y-%m-%d')
                    cursor.execute("INSERT INTO records (user_id, content, category, status, source_record_id, date) VALUES (?, ?, 'shopping', 'pending', ?, ?)", (user_id, shopping_content, record_id, record_date))
        else:
            # 当取消购买需求时，直接通过 source_record_id 删除对应的购物项
            cursor.execute("DELETE FROM records WHERE category = 'shopping' AND source_record_id = ? AND user_id = ?", (record_id, user_id))
        
        conn.commit()
    except (sqlite3.Error, ValueError) as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})



@app.route('/api/records/<int:record_id>/quantity', methods=['PUT'])
@login_required
def update_medicine_quantity(record_id):
    data = request.get_json()
    new_quantity = data.get('total_quantity')
    if new_quantity is None:
        return jsonify({"error": "total_quantity is required"}), 400

    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        cursor.execute("SELECT id FROM records WHERE id = ? AND category = 'medicine' AND user_id = ?", (record_id, user_id))
        if not cursor.fetchone():
            return jsonify({"error": "药品不存在或权限不足"}), 404
        
        new_start_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute("UPDATE records SET total_quantity = ?, start_date = ? WHERE id = ?", (new_quantity, new_start_date, record_id))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"status": "success"})

@app.route('/api/shopping/clear', methods=['POST'])
@login_required
def clear_shopping_list():
    """清空当前用户的所有购物清单项（包括已完成和未完成的）"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    user_id = current_user.id
    try:
        # 在删除前，获取所有购物项以处理关联的药品状态
        cursor.execute("SELECT source_record_id FROM records WHERE category = 'shopping' AND user_id = ? AND source_record_id IS NOT NULL", (user_id,))
        medicine_source_ids = [row['source_record_id'] for row in cursor.fetchall()]
        if medicine_source_ids:
            # 将所有关联药品的购买需求重置
            cursor.execute(f"UPDATE records SET needs_purchase = 0 WHERE id IN ({','.join('?' for _ in medicine_source_ids)}) AND user_id = ?", (*medicine_source_ids, user_id))

        # 删除所有购物项
        cursor.execute("DELETE FROM records WHERE category = 'shopping' AND user_id = ?", (user_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})


# --- 新增：为 uploads 目录提供静态文件服务 ---
from flask import send_from_directory

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)


# --- 页面服务 ---
@app.route('/')
@login_required
def index():
    return render_template('index.html')

@app.route('/<page_name>')
def show_page(page_name):
    if page_name in ['login', 'register']:
        return render_template(f'{page_name}.html')
    
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
        
    if page_name in ['medicine', 'clothes', 'shopping', 'people', 'profile']: # **新增** 'profile'
        return render_template(f'{page_name}.html')
        
    return "Page not found", 404

if __name__ == '__main__':
    app.run(debug=True)