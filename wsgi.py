import os
from app import create_app

app = create_app(os.getenv('FLASK_CONFIG', 'default'))

if __name__ == "__main__":
    host = os.environ.get('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.environ.get('FLASK_RUN_PORT', 5000))
    debug = app.debug
    
    app.run(host=host, port=port, debug=debug, use_reloader=False)
