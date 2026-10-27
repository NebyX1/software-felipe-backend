from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, IntegerField, EmailField, SelectField
from wtforms.validators import DataRequired, Email, Length, NumberRange, Optional


class AdminLoginForm(FlaskForm):
    email = EmailField("Correo Electrónico", validators=[DataRequired(), Email()])
    password = PasswordField("Contraseña", validators=[DataRequired()])
    captcha = IntegerField("Verificación", validators=[DataRequired()])


class TwoFAForm(FlaskForm):
    code = StringField(
        "Código de Seguridad",
        validators=[DataRequired(), Length(min=6, max=6)],
    )


class CreateUserForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=100)])
    email = EmailField("Correo", validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField("Contraseña", validators=[DataRequired(), Length(min=8, max=128)])
    role = SelectField(
        "Rol",
        choices=[("user", "Usuario"), ("admin", "Administrador"), ("super_admin", "Super Admin")],
        validators=[DataRequired()],
    )
    unit_id = SelectField("Unidad", coerce=int, validators=[Optional()])


class EditUserForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=100)])
    email = EmailField("Correo", validators=[DataRequired(), Email(), Length(max=150)])
    password = PasswordField(
        "Nueva Contraseña",
        validators=[Optional(), Length(min=8, max=128)],
    )
    role = SelectField(
        "Rol",
        choices=[("user", "Usuario"), ("admin", "Administrador"), ("super_admin", "Super Admin")],
        validators=[DataRequired()],
    )
    unit_id = SelectField("Unidad", coerce=int, validators=[Optional()])


class CreateUnitForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=150)])
    description = StringField("Descripción", validators=[Optional(), Length(max=500)])
    color = StringField("Color (hex)", validators=[DataRequired(), Length(min=4, max=20)])
    emoji = StringField("Emoji", validators=[DataRequired(), Length(max=16)])


class EditUnitForm(FlaskForm):
    name = StringField("Nombre", validators=[DataRequired(), Length(max=150)])
    description = StringField("Descripción", validators=[Optional(), Length(max=500)])
    color = StringField("Color (hex)", validators=[DataRequired(), Length(min=4, max=20)])
    emoji = StringField("Emoji", validators=[DataRequired(), Length(max=16)])
