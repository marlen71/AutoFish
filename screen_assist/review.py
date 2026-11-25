"""Local, explicit human annotation. No automatic ground-truth generation."""
import json
from pathlib import Path


def review(parent):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    from PIL import Image, ImageTk
    selected = filedialog.askdirectory(parent=parent, title='Папка сессии Assist_captures')
    if not selected:
        return
    folder = Path(selected)
    images = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.jpg', '.png'))
    if not images:
        messagebox.showinfo('НейроАссист', 'В папке нет кадров.', parent=parent)
        return
    annotations = folder / 'annotations.json'
    try:
        data = json.loads(annotations.read_text(encoding='utf-8')) if annotations.exists() else {}
    except Exception as exc:
        messagebox.showerror('Разметка', str(exc), parent=parent)
        return
    win = tk.Toplevel(parent)
    win.title('НейроАссист — проверка кадров')
    ttk.Label(win, text='Обведите ВСЕХ персонажей. Свой — отдельный класс. Союзников отличить нельзя.\n'
              'Сохранить без боксов = подтверждённый пустой кадр. Переход без сохранения отменяет правки.').pack()
    kind = tk.StringVar(value='Другой игрок')
    ttk.Combobox(win, textvariable=kind, values=['Другой игрок', 'Свой персонаж'], state='readonly').pack()
    canvas = tk.Canvas(win, width=960, height=600, bg='black')
    canvas.pack()
    status = tk.StringVar()
    ttk.Label(win, textvariable=status).pack()
    state = dict(index=0, boxes=[], start=None, scale=1., width=1, height=1)

    def redraw():
        canvas.delete('box')
        for cls, x1, y1, x2, y2 in state['boxes']:
            s = state['scale']
            canvas.create_rectangle(x1*s, y1*s, x2*s, y2*s, outline='red' if cls else '#00ff88', width=2, tags='box')

    def load():
        image = Image.open(images[state['index']]).convert('RGB')
        w, h = image.size
        state.update(width=w, height=h, scale=min(960/w, 600/h), start=None)
        image.thumbnail((960, 600))
        canvas.photo = ImageTk.PhotoImage(image)
        canvas.delete('all')
        canvas.create_image(0, 0, anchor='nw', image=canvas.photo)
        record = data.get(images[state['index']].name, {})
        state['boxes'] = [list(b) for b in record.get('boxes', [])]
        status.set(f"{state['index']+1}/{len(images)} — {images[state['index']].name} — " + ('проверен' if record.get('reviewed') else 'не проверен'))
        redraw()

    def point(event):
        return (max(0, min(state['width'], event.x/state['scale'])),
                max(0, min(state['height'], event.y/state['scale'])))

    def begin(event):
        state['start'] = point(event)

    def finish(event):
        if state['start'] is None:
            return
        x1, y1 = state['start']
        x2, y2 = point(event)
        state['start'] = None
        if abs(x2-x1) >= 5 and abs(y2-y1) >= 5:
            state['boxes'].append([int(kind.get() == 'Свой персонаж'), min(x1,x2), min(y1,y2), max(x1,x2), max(y1,y2)])
        redraw()

    def move(delta):
        state['index'] = max(0, min(len(images)-1, state['index']+delta))
        load()

    def save():
        data[images[state['index']].name] = dict(reviewed=True, boxes=state['boxes'])
        temporary = annotations.with_suffix('.tmp')
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(annotations)
        move(1)

    def undo():
        if state['boxes']:
            state['boxes'].pop()
            redraw()

    canvas.bind('<ButtonPress-1>', begin)
    canvas.bind('<ButtonRelease-1>', finish)
    row = ttk.Frame(win)
    row.pack(fill='x')
    for label, command in [('Назад', lambda: move(-1)), ('Пропустить', lambda: move(1)),
                            ('Убрать последний бокс', undo), ('Подтвердить и дальше', save)]:
        ttk.Button(row, text=label, command=command).pack(side='left', padx=4, pady=8)
    load()
    parent.wait_window(win)
