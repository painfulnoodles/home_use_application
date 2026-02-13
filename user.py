from flask_login import UserMixin

class User(UserMixin):
    def __init__(self, id, username, avatar=None):
        self.id = id
        self.username = username
        self.avatar = avatar

    @staticmethod
    def get(user_id):
        import sqlite3
        conn = sqlite3.connect('database.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE id = ?", (user_id,))
        user_row = cursor.fetchone()
        conn.close()
        if user_row:
            return User(id=user_row['id'], username=user_row['username'], avatar=user_row['avatar'])
        return None