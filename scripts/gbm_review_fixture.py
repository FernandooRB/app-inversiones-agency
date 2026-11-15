"""Generate only fictional GBM evidence for automated browser verification."""

import sys
from io import BytesIO
from pathlib import Path

from reportlab.pdfgen import canvas


def fictional_statement():
    output = BytesIO()
    page = canvas.Canvas(output)
    page.drawString(30, 800, "ESTADO DE CUENTA DE PERSONA FICTICIA")
    page.drawString(30, 780, "PORTAFOLIO AL 31-DIC-25 AL 30-ENE-26")
    labels = [
        "DEUDA",
        "RENTA VARIABLE",
        "VALORES EN CORTO",
        "FONDO DE FONDOS",
        "GARANTIAS",
        "OTRAS INVERSIONES",
        "CREDITOS DE MARGEN",
        "EFECTIVO",
        "DERIVADOS",
    ]
    for index, label in enumerate(labels):
        opening, closing = ("100.00", "150.01") if label == "EFECTIVO" else ("0.00", "0.00")
        page.drawString(30, 760 - 20 * index, f"{label} {opening} {closing} 0.00")
    page.drawString(30, 580, "VALOR DEL PORTAFOLIO 100.00 150.01 100.00")
    page.drawString(30, 540, "Titular: PERSONA FICTICIA Contrato: SYNTH12345 RFC: ABC010101AAA")
    page.setFont("Helvetica", 9)
    for index, note in enumerate(
        [
            "DATOS DE PRACTICA: el abono del 05 de enero es una aportacion externa propia "
            "al cierre del dia (EOD).",
            "Valuaciones verificadas ficticias: 2025-12-31 = 100.00 MXN; "
            "2026-01-05 = 150.00 MXN; 2026-01-30 = 150.00 MXN.",
            "El control impreso de 150.01 MXN conserva una diferencia de un centavo pendiente de revision.",
            "Propuesta ficticia: SIM-NEW, precio sin ajuste 10.00 MXN al 2026-01-30, lote 1, peso 0.4.",
            "Tarifa ficticia: comision 10 puntos base, minimo 0, IVA 0 y costo de mercado 0.",
            "Este archivo es ficticio para probar el recorrido; "
            "no es un estado autentico de un intermediario.",
        ]
    ):
        page.drawString(30, 510 - 14 * index, note)
    page.showPage()
    page.setFont("Helvetica", 12)
    for index, text in enumerate(
        [
            "TOTAL EFECTIVO 150.01 150.01",
            "MOVIMIENTOS DE OPERACIONES",
            "FECHA DESCRIPCION IMPORTE NETO SALDO",
            "31/12 0 EFECTIVO INICIAL 0.00 0.00 0.00 100.00 100.00",
            "05/05 1 DEPOSITO EFECTIVO 0.00 0.00 0.00 50.00 150.01",
            "MOVIMIENTOS DOCUMENTALES",
        ]
    ):
        page.drawString(30, 750 - 20 * index, text)
    page.showPage()
    page.save()
    return output.getvalue()


if __name__ == "__main__":
    Path(sys.argv[1]).write_bytes(fictional_statement())
