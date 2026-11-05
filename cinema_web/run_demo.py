import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tests"))
import sqlite_shim  

path = os.path.join(tempfile.gettempdir(), "cinema_demo.db")
if os.path.exists(path):
    os.remove(path)
sqlite_shim.install(path)

import cinema.db as dbm  
dbm.connect = lambda: sqlite_shim.Conn(path)
from cinema import create_app  

app = create_app()
if __name__ == "__main__":
    print("Mở http://127.0.0.1:5000 |  admin@cinema.vn / Admin@123")
    app.run(debug=False, port=5000)