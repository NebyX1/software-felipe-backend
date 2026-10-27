"""Email service for CivicFlow – Plataforma de Gestión Pública · IDL."""
from threading import Thread
from flask import current_app
from flask_mail import Message
from ..extensions import mail


def _send_async(app, msg: Message) -> None:
    with app.app_context():
        try:
            mail.send(msg)
        except Exception as exc:
            app.logger.error(f"Email send failed: {exc}")


def _send(subject: str, recipients: list[str], text: str, html: str) -> None:
    app = current_app._get_current_object()
    msg = Message(subject=subject, recipients=recipients)
    msg.body = text
    msg.html = html
    Thread(target=_send_async, args=(app, msg), daemon=True).start()


#  public helpers 


def send_2fa_email(to_email: str, user_name: str, code: str, app=None) -> None:
    """Send a 2-factor authentication code to the user."""
    _app = app or current_app._get_current_object()
    app_name = _app.config.get("APP_NAME", "CivicFlow")

    subject = f"[{app_name}] Código de verificación"
    text = (
        f"Hola {user_name},\n\n"
        f"Tu código de verificación de doble factor es: {code}\n"
        "Expira en 10 minutos.\n\n"
        "Si no iniciaste sesión, ignora este correo.\n\n"
        f"— {app_name} · Intendencia Departamental de Lavalleja"
    )
    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0" style="max-width:540px;width:100%;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);padding:24px 32px;text-align:center;">
            <div style="color:#ffffff;font-family:system-ui,Arial,sans-serif;font-size:22px;font-weight:800;letter-spacing:0.02em;line-height:1;">{app_name}</div>
            <div style="color:rgba(255,255,255,0.75);font-family:system-ui,Arial,sans-serif;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;margin-top:5px;">Plataforma de Gestión Pública</div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#ffffff;padding:36px 32px 28px;">
            <p style="font-family:system-ui,Arial,sans-serif;font-size:15px;color:#334155;margin:0 0 8px;">Hola <strong>{user_name}</strong>,</p>
            <p style="font-family:system-ui,Arial,sans-serif;font-size:14px;color:#64748b;margin:0 0 24px;">Tu código de verificación de doble factor es:</p>

            <!-- Code box -->
            <table width="100%" cellpadding="0" cellspacing="0" style="margin-bottom:24px;">
              <tr>
                <td align="center" style="background:#eef2ff;border-radius:10px;padding:20px 12px;">
                  <span style="font-family:'Courier New',monospace;font-size:38px;font-weight:700;letter-spacing:10px;color:#1e1b4b;display:inline-block;">{code}</span>
                </td>
              </tr>
            </table>

            <p style="font-family:system-ui,Arial,sans-serif;font-size:13px;color:#94a3b8;margin:0;">
              Expira en <strong style="color:#475569;">10 minutos</strong>.
              Si no eres tú, ignora este mensaje.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
            <p style="font-family:system-ui,Arial,sans-serif;font-size:11px;color:#94a3b8;margin:0;text-align:center;">
              {app_name} · Intendencia Departamental de Lavalleja<br>
              Este es un correo automático, por favor no responder.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""

    msg = Message(subject=subject, recipients=[to_email])
    msg.body = text
    msg.html = html

    Thread(
        target=_send_async, args=(_app, msg), daemon=True
    ).start()


def send_welcome_email(to_email: str, user_name: str, temp_password: str) -> None:
    """Send a welcome / credential email to a newly created user."""
    app = current_app._get_current_object()
    app_name = app.config.get("APP_NAME", "CivicFlow")
    frontend_url = app.config.get("FRONTEND_URL", "http://localhost:5173")

    subject = f"[{app_name}] Bienvenido/a — Credenciales de acceso"
    text = (
        f"Hola {user_name},\n\n"
        f"Tu cuenta ha sido creada en {app_name}.\n"
        f"Email: {to_email}\n"
        f"Contraseña temporal: {temp_password}\n\n"
        f"Accede en: {frontend_url}\n"
        "Te recomendamos cambiar tu contraseña tras el primer ingreso.\n\n"
        f"— {app_name} · Intendencia Departamental de Lavalleja"
    )
    html = f"""<!DOCTYPE html>
<html lang="es">
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f1f5f9;">
  <table width="100%" cellpadding="0" cellspacing="0" style="background:#f1f5f9;padding:32px 16px;">
    <tr><td align="center">
      <table width="540" cellpadding="0" cellspacing="0" style="max-width:540px;width:100%;border-radius:14px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

        <!-- Header -->
        <tr>
          <td style="background:linear-gradient(135deg,#6366f1 0%,#8b5cf6 100%);padding:24px 32px;text-align:center;">
            <div style="color:#ffffff;font-family:system-ui,Arial,sans-serif;font-size:22px;font-weight:800;letter-spacing:0.02em;line-height:1;">{app_name}</div>
            <div style="color:rgba(255,255,255,0.75);font-family:system-ui,Arial,sans-serif;font-size:11px;letter-spacing:0.1em;text-transform:uppercase;margin-top:5px;">Plataforma de Gestión Pública</div>
          </td>
        </tr>

        <!-- Body -->
        <tr>
          <td style="background:#ffffff;padding:36px 32px 28px;">
            <p style="font-family:system-ui,Arial,sans-serif;font-size:15px;color:#334155;margin:0 0 6px;">Hola <strong>{user_name}</strong>,</p>
            <p style="font-family:system-ui,Arial,sans-serif;font-size:14px;color:#64748b;margin:0 0 24px;">Tu cuenta ha sido creada en <strong style="color:#6366f1;">{app_name}</strong>. Aquí están tus credenciales de acceso:</p>

            <!-- Credentials box -->
            <table width="100%" cellpadding="0" cellspacing="0" style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:10px;margin-bottom:24px;">
              <tr>
                <td style="padding:14px 20px;border-bottom:1px solid #e2e8f0;">
                  <span style="font-family:system-ui,Arial,sans-serif;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.08em;display:block;margin-bottom:3px;">Email</span>
                  <span style="font-family:system-ui,Arial,sans-serif;font-size:14px;color:#334155;font-weight:500;">{to_email}</span>
                </td>
              </tr>
              <tr>
                <td style="padding:14px 20px;">
                  <span style="font-family:system-ui,Arial,sans-serif;font-size:11px;color:#94a3b8;text-transform:uppercase;letter-spacing:0.08em;display:block;margin-bottom:3px;">Contraseña temporal</span>
                  <span style="font-family:'Courier New',monospace;font-size:16px;color:#1e1b4b;font-weight:700;background:#eef2ff;padding:4px 10px;border-radius:6px;display:inline-block;">{temp_password}</span>
                </td>
              </tr>
            </table>

            <!-- CTA button -->
            <table cellpadding="0" cellspacing="0" style="margin-bottom:20px;">
              <tr>
                <td style="background:linear-gradient(135deg,#6366f1,#8b5cf6);border-radius:8px;">
                  <a href="{frontend_url}" style="display:inline-block;padding:12px 24px;color:#ffffff;font-family:system-ui,Arial,sans-serif;font-size:14px;font-weight:600;text-decoration:none;border-radius:8px;">
                    Ingresar a {app_name} →
                  </a>
                </td>
              </tr>
            </table>

            <p style="font-family:system-ui,Arial,sans-serif;font-size:12px;color:#94a3b8;margin:0;">
              Por seguridad, te recomendamos cambiar tu contraseña al ingresar por primera vez.
            </p>
          </td>
        </tr>

        <!-- Footer -->
        <tr>
          <td style="background:#f8fafc;padding:16px 32px;border-top:1px solid #e2e8f0;">
            <p style="font-family:system-ui,Arial,sans-serif;font-size:11px;color:#94a3b8;margin:0;text-align:center;">
              {app_name} · Intendencia Departamental de Lavalleja<br>
              Este es un correo automático, por favor no responder.
            </p>
          </td>
        </tr>

      </table>
    </td></tr>
  </table>
</body>
</html>"""
    _send(subject, [to_email], text, html)
