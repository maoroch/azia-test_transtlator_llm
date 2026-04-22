from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib import colors

doc = SimpleDocTemplate("table_sample.pdf", pagesize=letter)
data = [
    ["Term", "Definition"],
    ["PID", "Proportional-Integral-Derivative controller"],
    ["PLC", "Programmable Logic Controller"],
    ["HMI", "Human-Machine Interface"],
]
table = Table(data)
table.setStyle(TableStyle([
    ('GRID', (0,0), (-1,-1), 1, colors.black),
    ('BACKGROUND', (0,0), (-1,0), colors.grey),
    ('ALIGN', (0,0), (-1,-1), 'CENTER'),
]))
doc.build([table])
print("table_sample.pdf created")