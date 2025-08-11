from flask import Flask, render_template

app = Flask(__name__)

@app.route('/')
def home():
    return render_template('bank.html') # 确保 index.html 位于 templates 文件夹中

if __name__ == '__main__':
    app.run(debug=True)