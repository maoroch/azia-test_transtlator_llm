from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

c = canvas.Canvas("sample.pdf", pagesize=letter)
c.drawString(100, 750, "This is a test PDF for translation.")
c.drawString(100, 730, "It contains technical terms: PID controller, PLC, HMI.")
c.save()
print("sample.pdf created")