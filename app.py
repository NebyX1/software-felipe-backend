import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # Configuraciones de puerto y host para facilitar el inicio
    # host='0.0.0.0' permite conexiones externas (útil en Docker o Red Local)
    # port=5000 es el puerto por defecto de Flask
    # debug=True habilita el auto-reload y el debugger interactivo
    app.run(host='0.0.0.0', port=5000, debug=True)
