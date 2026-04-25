from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, PageBreak
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

def create_big_doc():
    doc = SimpleDocTemplate("big_doc.pdf", pagesize=A4,
                            leftMargin=2*cm, rightMargin=2*cm,
                            topMargin=2*cm, bottomMargin=2*cm)
    styles = getSampleStyleSheet()
    # Используем уникальные имена стилей
    styles.add(ParagraphStyle(name='CustomCode', fontName='Courier', fontSize=8, textColor=colors.darkblue))
    styles.add(ParagraphStyle(name='CustomHeading2', parent=styles['Heading2'], fontSize=12, textColor=colors.darkgreen))
    styles.add(ParagraphStyle(name='CustomBullet', parent=styles['Normal'], leftIndent=20, bulletIndent=10))

    story = []
    for i in range(1, 81):
        story.append(Paragraph(f"Section {i}: Technical Documentation", styles['CustomHeading2']))
        story.append(Spacer(1, 0.5*cm))
        story.append(Paragraph("This document describes the configuration and operational parameters of the industrial controller.", styles['Normal']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("The PID controller uses the following formula:", styles['Normal']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("u(t) = Kp e(t) + Ki ∫ e(τ) dτ + Kd de/dt", styles['CustomCode']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("Key parameters:", styles['Normal']))
        story.append(Paragraph("• Proportional gain (Kp): 2.5", styles['CustomBullet']))
        story.append(Paragraph("• Integral time (Ti): 0.1 s", styles['CustomBullet']))
        story.append(Paragraph("• Derivative time (Td): 0.05 s", styles['CustomBullet']))
        story.append(Spacer(1, 0.3*cm))
        story.append(Paragraph("The system also supports Modbus TCP/IP and PROFINET communication protocols.", styles['Normal']))
        if i < 80:
            story.append(PageBreak())
    doc.build(story)
    print("big_doc.pdf created (80 pages)")

if __name__ == "__main__":
    # Регистрируем шрифт (необязательно)
    try:
        pdfmetrics.registerFont(TTFont('Arial', '/System/Library/Fonts/Supplemental/Arial.ttf'))
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle(name='CustomCode', fontName='Courier', fontSize=8, textColor=colors.darkblue))
    except:
        pass
    create_big_doc()