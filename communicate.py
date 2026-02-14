from flask import Blueprint, request, jsonify
from flask_login import login_required, current_user
import sqlite3
from datetime import datetime
import json
import os
from werkzeug.utils import secure_filename
import uuid

# 创建一个蓝图
communicate_bp = Blueprint('communicate_bp', __name__)

def _get_db_conn():
    """获取数据库连接的辅助函数"""
    conn = sqlite3.connect('database.db', timeout=15)
    conn.row_factory = sqlite3.Row
    return conn

# --- 帖子 API ---

@communicate_bp.route('/api/posts', methods=['GET'])
@login_required
def get_posts():
    """获取所有帖子，包含作者、评论和点赞信息"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    
    # **关键修改**: 确保查询按 timestamp 降序排列
    cursor.execute("""
        SELECT p.id, p.content, p.timestamp, p.photos, u.username as author_username, u.avatar as author_avatar, p.user_id
        FROM posts p
        JOIN users u ON p.user_id = u.id
        ORDER BY p.timestamp DESC
    """)
    posts = [dict(row) for row in cursor.fetchall()]

    for post in posts:
        # 获取每个帖子的评论
        cursor.execute("""
            SELECT c.id, c.content, c.timestamp, u.username as author_username
            FROM comments c
            JOIN users u ON c.user_id = u.id
            WHERE c.post_id = ?
            ORDER BY c.timestamp ASC
        """, (post['id'],))
        post['comments'] = [dict(row) for row in cursor.fetchall()]

        # 获取每个帖子的点赞用户ID列表
        cursor.execute("SELECT user_id FROM likes WHERE post_id = ?", (post['id'],))
        post['likes'] = [row['user_id'] for row in cursor.fetchall()]
        
        # 检查当前用户是否是作者
        post['is_author'] = (post['user_id'] == current_user.id)
        
        # 解析照片
        try:
            post['photos'] = json.loads(post['photos']) if post['photos'] else []
        except (json.JSONDecodeError, TypeError):
            post['photos'] = []


    conn.close()
    return jsonify(posts)

@communicate_bp.route('/api/posts', methods=['POST'])
@login_required
def create_post():
    """
    创建一个新帖子。
    可以接收直接上传的文件 (photos) 或已存在的文件路径 (existing_photos)。
    """
    content = request.form.get('content')
    timestamp_str = request.form.get('timestamp', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    
    # 从表单中获取新上传的文件和已存在的路径
    new_photos = request.files.getlist('photos')
    existing_photos_json = request.form.get('existing_photos', '[]')

    if not content:
        return jsonify({"error": "内容不能为空"}), 400

    # 处理已存在的照片路径
    try:
        photo_paths = json.loads(existing_photos_json)
        if not isinstance(photo_paths, list):
            photo_paths = []
    except json.JSONDecodeError:
        photo_paths = []

    # 处理新上传的照片
    if new_photos:
        upload_folder = 'uploads'
        if not os.path.exists(upload_folder):
            os.makedirs(upload_folder)
        for photo in new_photos:
            if photo and photo.filename != '':
                base_filename = secure_filename(photo.filename)
                unique_filename = str(uuid.uuid4()) + os.path.splitext(base_filename)[1]
                filepath = os.path.join(upload_folder, unique_filename)
                photo.save(filepath)
                url_path = filepath.replace('\\', '/')
                photo_paths.append(url_path)

    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO posts (user_id, content, timestamp, photos) VALUES (?, ?, ?, ?)",
            (current_user.id, content, timestamp_str, json.dumps(photo_paths))
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"}), 201

@communicate_bp.route('/api/posts/<int:post_id>', methods=['PUT'])
@login_required
def update_post(post_id):
    """更新一个帖子"""
    content = request.form.get('content')
    timestamp_str = request.form.get('timestamp')

    if not content or not timestamp_str:
        return jsonify({"error": "内容和日期不能为空"}), 400

    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 验证权限
        cursor.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,))
        post = cursor.fetchone()
        if not post or post['user_id'] != current_user.id:
            return jsonify({"error": "权限不足或帖子不存在"}), 403

        cursor.execute(
            "UPDATE posts SET content = ?, timestamp = ? WHERE id = ?",
            (content, timestamp_str, post_id)
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})

@communicate_bp.route('/api/posts/<int:post_id>', methods=['DELETE'])
@login_required
def delete_post(post_id):
    """删除一个帖子"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 验证当前用户是否是帖子的作者
        cursor.execute("SELECT user_id FROM posts WHERE id = ?", (post_id,))
        post = cursor.fetchone()
        if not post or post['user_id'] != current_user.id:
            return jsonify({"error": "权限不足或帖子不存在"}), 403
        
        # 删除帖子、相关的评论和点赞
        cursor.execute("DELETE FROM comments WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM likes WHERE post_id = ?", (post_id,))
        cursor.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})

# --- 点赞 API ---

@communicate_bp.route('/api/posts/<int:post_id>/like', methods=['POST'])
@login_required
def toggle_like(post_id):
    """点赞或取消点赞一个帖子"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 检查是否已点赞
        cursor.execute("SELECT id FROM likes WHERE user_id = ? AND post_id = ?", (current_user.id, post_id))
        like = cursor.fetchone()

        if like:
            # 如果已点赞，则取消点赞
            cursor.execute("DELETE FROM likes WHERE id = ?", (like['id'],))
        else:
            # 如果未点赞，则添加点赞
            cursor.execute("INSERT INTO likes (user_id, post_id) VALUES (?, ?)", (current_user.id, post_id))
        
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})

# --- 评论 API ---

@communicate_bp.route('/api/posts/<int:post_id>/comments', methods=['POST'])
@login_required
def add_comment(post_id):
    """为帖子添加评论"""
    data = request.get_json()
    content = data.get('content')
    if not content:
        return jsonify({"error": "评论内容不能为空"}), 400

    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT INTO comments (post_id, user_id, content, timestamp) VALUES (?, ?, ?, ?)",
            (post_id, current_user.id, content, datetime.now())
        )
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"}), 201

@communicate_bp.route('/api/comments/<int:comment_id>', methods=['DELETE'])
@login_required
def delete_comment(comment_id):
    """删除一条评论"""
    conn = _get_db_conn()
    cursor = conn.cursor()
    try:
        # 验证当前用户是否是评论的作者
        cursor.execute("SELECT user_id FROM comments WHERE id = ?", (comment_id,))
        comment = cursor.fetchone()
        if not comment or comment['user_id'] != current_user.id:
            return jsonify({"error": "权限不足或评论不存在"}), 403
        
        cursor.execute("DELETE FROM comments WHERE id = ?", (comment_id,))
        conn.commit()
    except sqlite3.Error as e:
        conn.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        conn.close()
    return jsonify({"status": "success"})