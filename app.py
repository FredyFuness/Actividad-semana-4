import os
from datetime import datetime
from flask import Flask, render_template, redirect, url_for, request, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)

# Configuración de Clave Secreta
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'desarrollo-clave-secreta-local')

# Configuración de la Base de Datos PostgreSQL / Local
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    db_url = 'sqlite:///finanzas.db'

# Corrección de protocolo para Render
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Configuración de Flask-Login
login_manager = LoginManager(app)
login_manager.login_view = 'login'

# --- MODELOS DE LA BASE DE DATOS ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    transactions = db.relationship('Transaction', backref='owner', lazy=True, cascade="all, delete-orphan")

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    amount = db.Column(db.Float, nullable=False)
    description = db.Column(db.String(200), nullable=False)
    category = db.Column(db.String(50), nullable=False)
    type = db.Column(db.String(20), nullable=False)  # 'Ingreso' o 'Gasto'
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- RUTAS DE AUTENTICACIÓN ---
@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')

        user_exists = User.query.filter_by(username=username).first()
        if user_exists:
            flash('El nombre de usuario ya está registrado.', 'danger')
            return redirect(url_for('register'))

        hashed_password = generate_password_hash(password, method='scrypt')
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()

        flash('Registro exitoso. ¡Inicia sesión!', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form.get('username').strip()
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('Usuario o contraseña incorrectos.', 'danger')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Has cerrado sesión correctamente.', 'info')
    return redirect(url_for('login'))

# --- RUTAS DEL CRUD (FINANZAS) ---
@app.route('/dashboard', methods=['GET', 'POST'])
@login_required
def dashboard():
    if request.method == 'POST':
        amount = float(request.form.get('amount'))
        description = request.form.get('description')
        category = request.form.get('category')
        trans_type = request.form.get('type')
        date_str = request.form.get('date')
        
        trans_date = datetime.strptime(date_str, '%Y-%m-%d').date() if date_str else datetime.utcnow().date()

        new_transaction = Transaction(
            amount=amount,
            description=description,
            category=category,
            type=trans_type,
            date=trans_date,
            user_id=current_user.id
        )
        db.session.add(new_transaction)
        db.session.commit()
        flash('Transacción agregada con éxito.', 'success')
        return redirect(url_for('dashboard'))

    # Filtro estricto: Solo transacciones del usuario actual
    transactions = Transaction.query.filter_by(user_id=current_user.id).order_by(Transaction.date.desc()).all()

    # Cálculo de métricas
    total_ingresos = sum(t.amount for t in transactions if t.type == 'Ingreso')
    total_gastos = sum(t.amount for t in transactions if t.type == 'Gasto')
    saldo_total = total_ingresos - total_gastos

    return render_template('dashboard.html', 
                           transactions=transactions, 
                           saldo_total=saldo_total, 
                           total_ingresos=total_ingresos, 
                           total_gastos=total_gastos)

@app.route('/transaction/edit/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_transaction(id):
    transaction = Transaction.query.get_or_404(id)

    # Verificación de aislamiento
    if transaction.user_id != current_user.id:
        flash('Acceso denegado: No puedes editar este registro.', 'danger')
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        transaction.amount = float(request.form.get('amount'))
        transaction.description = request.form.get('description')
        transaction.category = request.form.get('category')
        transaction.type = request.form.get('type')
        transaction.date = datetime.strptime(request.form.get('date'), '%Y-%m-%d').date()

        db.session.commit()
        flash('Transacción actualizada correctamente.', 'success')
        return redirect(url_for('dashboard'))

    return render_template('edit_transaction.html', transaction=transaction)

@app.route('/transaction/delete/<int:id>', methods=['POST'])
@login_required
def delete_transaction(id):
    transaction = Transaction.query.get_or_404(id)

    # Verificación de aislamiento
    if transaction.user_id != current_user.id:
        flash('Acceso denegado: No puedes eliminar este registro.', 'danger')
        return redirect(url_for('dashboard'))

    db.session.delete(transaction)
    db.session.commit()
    flash('Transacción eliminada correctamente.', 'success')
    return redirect(url_for('dashboard'))

# Inicialización automática de tablas en PostgreSQL
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(debug=True)
    