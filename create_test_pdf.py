
from pathlib import Path
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet

data_dir = Path("data")
data_dir.mkdir(exist_ok=True)

pdf_path = data_dir / "attention.pdf"

doc = SimpleDocTemplate(str(pdf_path), pagesize=A4)
styles = getSampleStyleSheet()

content = [
    Paragraph("Artificial Intelligence - Test Document", styles["Title"]),
    Spacer(1, 20),
    Paragraph(
        "Machine Learning is a branch of Artificial Intelligence "
        "that enables computers to learn patterns from data.",
        styles["BodyText"],
    ),
    Spacer(1, 12),
    Paragraph(
        "Supervised Learning uses labeled data. "
        "Examples include classification and regression.",
        styles["BodyText"],
    ),
    Spacer(1, 12),
    Paragraph(
        "Unsupervised Learning works with unlabeled data. "
        "Clustering is one of its common applications.",
        styles["BodyText"],
    ),
    Spacer(1, 12),
    Paragraph(
        "RAG means Retrieval-Augmented Generation. "
        "It retrieves relevant information from documents "
        "and provides that information to a language model "
        "to help generate an answer.",
        styles["BodyText"],
    ),
]

doc.build(content)

print(f"PDF created successfully: {pdf_path.resolve()}")
