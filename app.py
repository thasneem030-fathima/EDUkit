import os, sqlite3, uuid
from functools import wraps
from flask import Flask, g, render_template, request, redirect, url_for, session, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'edukit.db')
app = Flask(__name__)
app.secret_key = 'change-this-secret-key'
app.config['UPLOAD_FOLDER'] = os.path.join(BASE, 'static', 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024  # 2 MB uploads

CATEGORIES = ['School Uniforms', 'College Uniforms', 'Sportswear', 'Shoes & Socks',
              'Stationery', 'Corporate Apparel', 'Corporate Gifts', 'Trophies & Medals']
EMOJI = dict(zip(CATEGORIES, ['👕', '🎓', '🏃', '👟', '📓', '👔', '🎁', '🏆']))
STATUSES = ['Placed', 'Packed', 'Shipped', 'Delivered', 'Cancelled']
ALLOWED = {'png', 'jpg', 'jpeg', 'gif'}
app.jinja_env.globals['EMOJI'] = EMOJI

# ---------- database helpers ----------
def db():
    if 'db' not in g:
        g.db = sqlite3.connect(DB)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e):
    d = g.pop('db', None)
    if d:
        d.close()

def q(sql, args=(), one=False):
    cur = db().execute(sql, args)
    rows = cur.fetchall()
    db().commit()
    return (rows[0] if rows else None) if one else rows

# ---------- helpers ----------
def login_required(f):
    @wraps(f)
    def w(*a, **k):
        if 'uid' not in session:
            flash('Please login first.')
            return redirect(url_for('login', next=request.path))
        return f(*a, **k)
    return w

def admin_required(f):
    @wraps(f)
    def w(*a, **k):
        if not session.get('admin'):
            flash('Admin access only.')
            return redirect(url_for('login'))
        return f(*a, **k)
    return w

def save_file(f):
    if f and f.filename and f.filename.rsplit('.', 1)[-1].lower() in ALLOWED:
        name = uuid.uuid4().hex[:10] + '_' + secure_filename(f.filename)
        f.save(os.path.join(app.config['UPLOAD_FOLDER'], name))
        return name
    return ''

def cart_items():
    items, subtotal, qty = [], 0, 0
    for i, c in enumerate(session.get('cart', [])):
        p = q('SELECT * FROM products WHERE id=?', (c['pid'],), one=True)
        if not p:
            continue
        line = p['price'] * c['qty']
        items.append(dict(idx=i, p=p, line=line, **c))
        subtotal += line
        qty += c['qty']
    # bulk discount: 10+ items 5%, 50+ items 10%, 100+ items 15%
    pct = 15 if qty >= 100 else 10 if qty >= 50 else 5 if qty >= 10 else 0
    disc = round(subtotal * pct / 100, 2)
    return items, subtotal, pct, disc, subtotal - disc

@app.context_processor
def inject_cart():
    return {'cart_count': sum(c['qty'] for c in session.get('cart', []))}

# ---------- shop pages ----------
@app.route('/')
def index():
    feat = q('SELECT * FROM products ORDER BY id DESC LIMIT 8')
    return render_template('index.html', feat=feat, cats=CATEGORIES)

@app.route('/products')
def products():
    cat = request.args.get('category', '')
    s = request.args.get('q', '').strip()
    mx = request.args.get('max', '')
    sql, args = 'SELECT * FROM products WHERE 1=1', []
    if cat:
        sql += ' AND category=?'
        args.append(cat)
    if s:
        sql += ' AND (name LIKE ? OR description LIKE ?)'
        args += [f'%{s}%'] * 2
    if mx.isdigit():
        sql += ' AND price<=?'
        args.append(int(mx))
    return render_template('products.html', items=q(sql + ' ORDER BY name', args),
                           cats=CATEGORIES, cat=cat, s=s, mx=mx)

@app.route('/product/<int:pid>')
def product(pid):
    p = q('SELECT * FROM products WHERE id=?', (pid,), one=True)
    if not p:
        return 'Product not found', 404
    return render_template('product.html', p=p)

@app.route('/bulk')
def bulk():
    return render_template('bulk.html')

@app.route('/size-chart')
def size_chart():
    return render_template('size_chart.html')

# ---------- cart and checkout ----------
@app.route('/cart/add/<int:pid>', methods=['POST'])
def cart_add(pid):
    p = q('SELECT * FROM products WHERE id=?', (pid,), one=True)
    qty = max(1, int(request.form.get('qty') or 1))
    if not p or p['stock'] < qty:
        flash('Not enough stock.')
        return redirect(url_for('product', pid=pid))
    cart = session.get('cart', [])
    cart.append(dict(pid=pid, qty=qty, size=request.form.get('size', ''),
                     colour=request.form.get('colour', ''),
                     text=request.form.get('text', '')[:40],
                     logo=save_file(request.files.get('logo'))))
    session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/cart')
def cart():
    items, sub, pct, disc, total = cart_items()
    return render_template('cart.html', items=items, sub=sub, pct=pct, disc=disc, total=total)

@app.route('/cart/remove/<int:i>')
def cart_remove(i):
    cart = session.get('cart', [])
    if 0 <= i < len(cart):
        cart.pop(i)
        session['cart'] = cart
    return redirect(url_for('cart'))

@app.route('/checkout', methods=['GET', 'POST'])
@login_required
def checkout():
    items, sub, pct, disc, total = cart_items()
    if not items:
        return redirect(url_for('cart'))
    if request.method == 'POST':
        con = db()
        cur = con.execute(
            "INSERT INTO orders(user_id,total,discount,status,address,institution,created) "
            "VALUES(?,?,?,?,?,?,datetime('now'))",
            (session['uid'], total, disc, 'Placed', request.form['address'],
             request.form.get('institution', '')))
        oid = cur.lastrowid
        for it in items:
            p = it['p']
            con.execute('INSERT INTO order_items(order_id,product_id,name,qty,price,size,colour,custom_text,logo) '
                        'VALUES(?,?,?,?,?,?,?,?,?)',
                        (oid, p['id'], p['name'], it['qty'], p['price'], it['size'],
                         it['colour'], it['text'], it['logo']))
            con.execute('UPDATE products SET stock=stock-? WHERE id=?', (it['qty'], p['id']))
        con.commit()
        session.pop('cart', None)
        flash('Payment successful (demo). Your order is placed!')
        return redirect(url_for('order_detail', oid=oid))
    return render_template('checkout.html', items=items, sub=sub, pct=pct, disc=disc, total=total)

@app.route('/orders')
@login_required
def orders():
    rows = q('SELECT * FROM orders WHERE user_id=? ORDER BY id DESC', (session['uid'],))
    return render_template('orders.html', orders=rows)

@app.route('/order/<int:oid>')
@login_required
def order_detail(oid):
    o = q('SELECT * FROM orders WHERE id=?', (oid,), one=True)
    if not o or (o['user_id'] != session['uid'] and not session.get('admin')):
        return 'Order not found', 404
    items = q('SELECT * FROM order_items WHERE order_id=?', (oid,))
    return render_template('order_detail.html', o=o, items=items, idx=STATUSES.index(o['status']))

# ---------- accounts ----------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        f = request.form
        if q('SELECT 1 FROM users WHERE email=?', (f['email'],), one=True):
            flash('Email already registered.')
        else:
            q('INSERT INTO users(name,email,password,institution) VALUES(?,?,?,?)',
              (f['name'], f['email'], generate_password_hash(f['password']), f.get('institution', '')))
            flash('Account created. Please login.')
            return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        u = q('SELECT * FROM users WHERE email=?', (request.form['email'],), one=True)
        if u and check_password_hash(u['password'], request.form['password']):
            session.update(uid=u['id'], uname=u['name'], admin=bool(u['is_admin']))
            nxt = request.args.get('next', '')
            return redirect(nxt if nxt.startswith('/') else url_for('index'))
        flash('Wrong email or password.')
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('index'))

# ---------- admin ----------
@app.route('/admin')
@admin_required
def admin():
    stats = q("SELECT COUNT(*) n, COALESCE(SUM(total),0) rev FROM orders WHERE status!='Cancelled'", one=True)
    top = q('SELECT name, SUM(qty) units FROM order_items GROUP BY name ORDER BY units DESC LIMIT 5')
    prods = q('SELECT * FROM products ORDER BY id DESC')
    orders = q('SELECT o.*, u.name uname FROM orders o JOIN users u ON u.id=o.user_id ORDER BY o.id DESC')
    users = q('SELECT * FROM users WHERE is_admin=0')
    return render_template('admin.html', stats=stats, top=top, prods=prods,
                           orders=orders, users=users, statuses=STATUSES)

@app.route('/admin/product', methods=['GET', 'POST'])
@app.route('/admin/product/<int:pid>', methods=['GET', 'POST'])
@admin_required
def admin_product(pid=None):
    p = q('SELECT * FROM products WHERE id=?', (pid,), one=True) if pid else None
    if request.method == 'POST':
        f = request.form
        img = save_file(request.files.get('image')) or (p['image'] if p else '')
        vals = (f['name'], f['category'], f['description'], float(f['price']),
                int(f['stock']), img, 1 if f.get('customizable') else 0)
        if p:
            q('UPDATE products SET name=?,category=?,description=?,price=?,stock=?,image=?,customizable=? WHERE id=?',
              vals + (pid,))
        else:
            q('INSERT INTO products(name,category,description,price,stock,image,customizable) VALUES(?,?,?,?,?,?,?)', vals)
        flash('Product saved.')
        return redirect(url_for('admin'))
    return render_template('product_form.html', p=p, cats=CATEGORIES)

@app.route('/admin/delete/<int:pid>', methods=['POST'])
@admin_required
def admin_delete(pid):
    q('DELETE FROM products WHERE id=?', (pid,))
    return redirect(url_for('admin'))

@app.route('/admin/order/<int:oid>', methods=['POST'])
@admin_required
def admin_order(oid):
    q('UPDATE orders SET status=? WHERE id=?', (request.form['status'], oid))
    return redirect(url_for('admin'))

# ---------- JSON API (used for integration with other websites) ----------
@app.route('/api/products')
def api_products():
    return jsonify([dict(r) for r in q('SELECT id,name,category,price,image FROM products')])

# ---------- create tables + sample data ----------
SCHEMA = '''
CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, email TEXT UNIQUE,
  password TEXT, institution TEXT DEFAULT '', is_admin INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS products(id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, category TEXT,
  description TEXT, price REAL, stock INTEGER, image TEXT DEFAULT '', customizable INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, total REAL,
  discount REAL, status TEXT, address TEXT, institution TEXT, created TEXT);
CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER,
  product_id INTEGER, name TEXT, qty INTEGER, price REAL, size TEXT, colour TEXT, custom_text TEXT, logo TEXT);
'''

SEED = [
    ('School Uniform Shirt', 'School Uniforms', 'Cotton shirt, durable and easy to wash.', 350, 200, 1),
    ('School Uniform Trousers', 'School Uniforms', 'Comfortable fit trousers for daily wear.', 450, 150, 0),
    ('College Blazer', 'College Uniforms', 'Formal blazer with embroidery option.', 1800, 60, 1),
    ('Track Suit', 'Sportswear', 'Track shirt and pants set for sports day.', 1100, 80, 1),
    ('Custom Sports Jersey', 'Sportswear', 'Dry-fit jersey with name and number.', 600, 120, 1),
    ('School Shoes', 'Shoes & Socks', 'Black leather school shoes.', 900, 90, 0),
    ('Sports Socks (Pack of 3)', 'Shoes & Socks', 'Cotton socks, pack of 3.', 199, 300, 0),
    ('Notebook Set (Pack of 6)', 'Stationery', 'Ruled notebooks, 180 pages each.', 320, 250, 0),
    ('Corporate Logo T-Shirt', 'Corporate Apparel', 'Premium cotton T-shirt with your company logo.', 499, 400, 1),
    ('Corporate Gift Hamper', 'Corporate Gifts', 'Pen, diary, mug and keychain gift set.', 950, 70, 1),
    ('Winner Trophy', 'Trophies & Medals', 'Gold finish trophy with name plate.', 650, 100, 1),
    ('Gold Medal (Pack of 10)', 'Trophies & Medals', 'Medals with ribbon for events.', 800, 60, 0),
]

def init_db():
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)
    if not con.execute('SELECT 1 FROM users').fetchone():
        con.execute('INSERT INTO users(name,email,password,is_admin) VALUES(?,?,?,1)',
                    ('Admin', 'admin@edukit.com', generate_password_hash('admin123')))
    if not con.execute('SELECT 1 FROM products').fetchone():
        con.executemany('INSERT INTO products(name,category,description,price,stock,customizable) '
                        'VALUES(?,?,?,?,?,?)', SEED)
    con.commit()
    con.close()

init_db()

if __name__ == '__main__':
    app.run(debug=True)
