import yfinance as yf
import pandas as pd
import numpy as np

from datetime import datetime, date
from scipy.optimize import minimize
from scipy.stats import norm

import streamlit as st
import plotly.express as px
import plotly.graph_objects as go

# --- IMPORTS NUEVOS PARA PDF ---
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle
from reportlab.lib.utils import ImageReader  # <--- AGREGA ESTA LÍNEA
import io

class PortfolioManager:

    """

    Clase para gestionar y analizar portafolios de inversión.

    """

   

    def __init__(self, tickers, start_date, end_date):

        """

        Inicializa el PortfolioManager.

       

        Parameters:

        -----------

        tickers : list

            Lista de símbolos de tickers (ej. ['SPY', 'QQQ', 'GLD'])

        start_date : str

            Fecha de inicio en formato 'YYYY-MM-DD'

        end_date : str

            Fecha de fin en formato 'YYYY-MM-DD'

        """

        self.tickers = tickers

        self.start_date = start_date

        self.end_date = end_date

        self.data = None

        self.log_returns = None

        self.cov_matrix = None

        self.corr_matrix = None

        self.mean_returns = None

   

    def fetch_data(self):

        """

        Descarga los precios de cierre ajustados para los tickers especificados.

        Maneja el caso en que los datos vengan vacíos.

        """

        try:

            # Descargar datos ticker por ticker usando el objeto Ticker

            data_list = []

            valid_tickers = []

           

            for ticker in self.tickers:

                try:

                    ticker_obj = yf.Ticker(ticker)

                    ticker_data = ticker_obj.history(

                        start=self.start_date,

                        end=self.end_date

                    )

                   

                    if ticker_data.empty:

                        print(f"Advertencia: No se pudieron descargar datos para {ticker}")

                        continue

                   

                    if 'Close' not in ticker_data.columns:

                        print(f"Advertencia: No se encontró 'Close' para {ticker}")

                        continue

                   

                    # Calcular el precio ajustado manualmente

                    # El precio ajustado se calcula ajustando por dividendos y splits

                    adj_close = ticker_data['Close'].copy()

                   

                    # Ajustar por stock splits y dividendos (ajuste hacia atrás)

                    # Empezamos desde la fecha más reciente y vamos hacia atrás

                    if 'Stock Splits' in ticker_data.columns or 'Dividends' in ticker_data.columns:

                        # Invertir el orden para ajustar desde el presente hacia el pasado

                        adj_close_reversed = adj_close.iloc[::-1].copy()

                        split_factor = 1.0

                       

                        if 'Stock Splits' in ticker_data.columns:

                            splits_reversed = ticker_data['Stock Splits'].iloc[::-1]

                            for i in range(len(adj_close_reversed)):

                                if splits_reversed.iloc[i] > 0:

                                    split_factor *= (1 + splits_reversed.iloc[i])

                                adj_close_reversed.iloc[i] *= split_factor

                       

                        if 'Dividends' in ticker_data.columns:

                            dividends_reversed = ticker_data['Dividends'].iloc[::-1]

                            for i in range(len(adj_close_reversed)):

                                if dividends_reversed.iloc[i] > 0:

                                    # Ajustar por dividendos: precio_ajustado = precio_original - dividendo

                                    adj_close_reversed.iloc[i] -= dividends_reversed.iloc[i]

                       

                        # Volver al orden original

                        adj_close = adj_close_reversed.iloc[::-1]

                   

                    # Crear DataFrame con el precio ajustado

                    adj_close_df = pd.DataFrame({ticker: adj_close})

                    data_list.append(adj_close_df)

                    valid_tickers.append(ticker)

                   

                except Exception as e:

                    print(f"Error al descargar {ticker}: {str(e)}")

                    continue

           

            if not data_list:

                raise ValueError(f"No se pudieron descargar datos para ninguno de los tickers: {self.tickers}")

           

            # Combinar todos los DataFrames

            self.data = pd.concat(data_list, axis=1)

           

            # Eliminar filas con valores NaN

            self.data = self.data.dropna()

           

            if self.data.empty:

                raise ValueError("Los datos descargados están vacíos después de eliminar NaN")

           

            # Actualizar la lista de tickers con los que funcionaron

            self.tickers = valid_tickers

           

            print(f"Datos descargados exitosamente para {len(valid_tickers)} ticker(s). Shape: {self.data.shape}")

            return self.data

           

        except Exception as e:

            print(f"Error al descargar datos: {str(e)}")

            raise

   

    def calculate_basic_metrics(self):

        """

        Calcula métricas básicas del portafolio:

        - Retornos logarítmicos diarios

        - Matriz de covarianza anualizada (multiplicada por 252)

        - Matriz de correlación

        """

        if self.data is None:

            raise ValueError("Debe descargar los datos primero usando fetch_data()")

       

        # Calcular retornos logarítmicos diarios: log(Pt / Pt-1)

        self.log_returns = np.log(self.data / self.data.shift(1))

        self.log_returns = self.log_returns.dropna()

       

        # Calcular matriz de covarianza anualizada (multiplicar por 252 días de trading)

        self.cov_matrix = self.log_returns.cov() * 252

       

        # Calcular matriz de correlación

        self.corr_matrix = self.log_returns.corr()

       

        # Calcular retornos medios anualizados (multiplicar por 252 días de trading)

        self.mean_returns = self.log_returns.mean() * 252

       

        print("Métricas básicas calculadas exitosamente.")

        return {

            'log_returns': self.log_returns,

            'cov_matrix': self.cov_matrix,

            'corr_matrix': self.corr_matrix,

            'mean_returns': self.mean_returns

        }

   

    def get_ret_vol_sr(self, weights, risk_free_rate=0.02):

        """

        Método auxiliar que calcula retorno esperado, volatilidad y Sharpe Ratio

        para un conjunto de pesos dado.

       

        Parameters:

        -----------

        weights : array-like

            Array de pesos del portafolio (debe sumar 1)

        risk_free_rate : float

            Tasa libre de riesgo anual (default: 0.02 = 2%)

       

        Returns:

        --------

        array : [Retorno Esperado, Volatilidad, Sharpe Ratio]

        """

        if self.mean_returns is None or self.cov_matrix is None:

            raise ValueError("Debe calcular las métricas básicas primero usando calculate_basic_metrics()")

       

        weights = np.array(weights)

       

        # Retorno esperado del portafolio

        portfolio_return = np.sum(self.mean_returns * weights)

       

        # Volatilidad del portafolio (desviación estándar anualizada)

        portfolio_volatility = np.sqrt(np.dot(weights.T, np.dot(self.cov_matrix, weights)))

       

        # Sharpe Ratio

        sharpe_ratio = (portfolio_return - risk_free_rate) / portfolio_volatility

       

        return np.array([portfolio_return, portfolio_volatility, sharpe_ratio])

   

    def optimize_sharpe_ratio(self, risk_free_rate=0.02):

        """

        Optimiza los pesos del portafolio para maximizar el Sharpe Ratio.

       

        Parameters:

        -----------

        risk_free_rate : float

            Tasa libre de riesgo anual (default: 0.02 = 2%)

       

        Returns:

        --------

        dict : Diccionario con los pesos óptimos y métricas del portafolio

        """

        if self.mean_returns is None or self.cov_matrix is None:

            raise ValueError("Debe calcular las métricas básicas primero usando calculate_basic_metrics()")

       

        num_assets = len(self.tickers)

       

        # Función objetivo: minimizar el negativo del Sharpe Ratio

        def negative_sharpe(weights):

            ret_vol_sr = self.get_ret_vol_sr(weights, risk_free_rate)

            return -ret_vol_sr[2]  # Retornar el negativo del Sharpe Ratio

       

        # Restricción: la suma de pesos debe ser 1

        constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})

       

        # Límites: cada peso entre 0 y 1 (sin ventas en corto)

        bounds = tuple((0, 1) for _ in range(num_assets))

       

        # Punto inicial: pesos iguales (1/n para cada activo)

        initial_weights = np.array([1/num_assets] * num_assets)

       

        # Optimizar

        result = minimize(

            negative_sharpe,

            initial_weights,

            method='SLSQP',

            bounds=bounds,

            constraints=constraints

        )

       

        if not result.success:

            raise ValueError(f"La optimización falló: {result.message}")

       

        optimal_weights = result.x

       

        # Calcular métricas del portafolio óptimo

        ret_vol_sr = self.get_ret_vol_sr(optimal_weights, risk_free_rate)

       

        return {

            'weights': optimal_weights,

            'expected_return': ret_vol_sr[0],

            'volatility': ret_vol_sr[1],

            'sharpe_ratio': ret_vol_sr[2]

        }

   

    def optimize_min_volatility(self):

        """

        Optimiza los pesos del portafolio para minimizar la volatilidad.

       

        Returns:

        --------

        dict : Diccionario con los pesos óptimos y métricas del portafolio

        """

        if self.mean_returns is None or self.cov_matrix is None:

            raise ValueError("Debe calcular las métricas básicas primero usando calculate_basic_metrics()")

       

        num_assets = len(self.tickers)

       

        # Función objetivo: minimizar la volatilidad

        def portfolio_volatility(weights):

            ret_vol_sr = self.get_ret_vol_sr(weights)

            return ret_vol_sr[1]  # Retornar la volatilidad

       

        # Restricción: la suma de pesos debe ser 1

        constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})

       

        # Límites: cada peso entre 0 y 1 (sin ventas en corto)

        bounds = tuple((0, 1) for _ in range(num_assets))

       

        # Punto inicial: pesos iguales (1/n para cada activo)

        initial_weights = np.array([1/num_assets] * num_assets)

       

        # Optimizar

        result = minimize(

            portfolio_volatility,

            initial_weights,

            method='SLSQP',

            bounds=bounds,

            constraints=constraints

        )

       

        if not result.success:

            raise ValueError(f"La optimización falló: {result.message}")

       

        optimal_weights = result.x

       

        # Calcular métricas del portafolio óptimo

        ret_vol_sr = self.get_ret_vol_sr(optimal_weights)

       

        return {

            'weights': optimal_weights,

            'expected_return': ret_vol_sr[0],

            'volatility': ret_vol_sr[1],

            'sharpe_ratio': ret_vol_sr[2]

        }

   

    def simulate_monte_carlo(self, num_sims=5000, risk_free_rate=0.02):

        """

        Simula múltiples escenarios de portafolio usando Monte Carlo.

        Genera pesos aleatorios y calcula métricas para cada simulación.

       

        Parameters:

        -----------

        num_sims : int

            Número de simulaciones a realizar (default: 5000)

        risk_free_rate : float

            Tasa libre de riesgo anual (default: 0.02 = 2%)

       

        Returns:

        --------

        DataFrame : DataFrame con columnas ['Retorno', 'Volatilidad', 'Sharpe', 'Pesos']

        """

        if self.mean_returns is None or self.cov_matrix is None:

            raise ValueError("Debe calcular las métricas básicas primero usando calculate_basic_metrics()")

       

        num_assets = len(self.tickers)

        results = []

       

        print(f"Ejecutando {num_sims} simulaciones de Monte Carlo...")

       

        for i in range(num_sims):

            # Generar pesos aleatorios que sumen 1

            # Usar distribución Dirichlet para generar pesos que sumen 1

            random_weights = np.random.dirichlet(np.ones(num_assets))

           

            # Calcular métricas para estos pesos

            ret_vol_sr = self.get_ret_vol_sr(random_weights, risk_free_rate)

           

            # Almacenar resultados

            results.append({

                'Retorno': ret_vol_sr[0],

                'Volatilidad': ret_vol_sr[1],

                'Sharpe': ret_vol_sr[2],

                'Pesos': random_weights.copy()

            })

       

        # Crear DataFrame con los resultados

        monte_carlo_df = pd.DataFrame(results)

       

        return monte_carlo_df

   

    def calculate_var_cvar(self, weights=None, confidence_level=0.95):
        """
        Calcula el Value at Risk (VaR) y Conditional VaR (CVaR) DIARIOS.
        """
        if self.mean_returns is None or self.cov_matrix is None:
            raise ValueError("Debe calcular las métricas básicas primero")
        
        if self.log_returns is None:
            raise ValueError("Los retornos logarítmicos no están disponibles")
        
        # Si no se proporcionan pesos, usar los óptimos de máximo Sharpe
        if weights is None:
            sharpe_result = self.optimize_sharpe_ratio()
            weights = sharpe_result['weights']
        
        weights = np.array(weights)
        
        # --- CORRECCIÓN 1: VaR Paramétrico (Usar Volatilidad DIARIA) ---
        # self.cov_matrix está anualizada (x252), así que la dividimos para volver a diario
        daily_cov_matrix = self.cov_matrix / 252
        portfolio_daily_volatility = np.sqrt(np.dot(weights.T, np.dot(daily_cov_matrix, weights)))
        
        # z_score para el nivel de confianza (1.645 para 95%)
        z_score = abs(norm.ppf(1 - confidence_level))
        
        # VaR Paramétrico Diario
        var_parametric = -z_score * portfolio_daily_volatility
        
        # --- CORRECCIÓN 2: VaR Histórico (Usar Retornos REALES, sin multiplicar por 252) ---
        # Calculamos los retornos diarios históricos del portafolio
        portfolio_returns_historical = (self.log_returns * weights).sum(axis=1)
        
        # VaR histórico: percentil de pérdidas diarias
        var_historical = np.percentile(portfolio_returns_historical, (1 - confidence_level) * 100)
        
        # --- CORRECCIÓN 3: CVaR (Promedio de pérdidas en días malos) ---
        losses_below_var = portfolio_returns_historical[portfolio_returns_historical <= var_historical]
        
        if len(losses_below_var) > 0:
            cvar = losses_below_var.mean()
        else:
            cvar = var_historical
        
        # Retornamos un diccionario (igual que antes) para no romper tu código de Streamlit
        return {
            'var_parametric': var_parametric,
            'var_historical': var_historical,
            'cvar': cvar,
            'confidence_level': confidence_level
        }



# ==========================================
# FUNCIÓN GENERADORA DE PDF
# ==========================================
# ==========================================
# FUNCIÓN GENERADORA DE PDF (DISEÑO CORREGIDO V2)
# ==========================================
# ==========================================
# FUNCIÓN GENERADORA DE PDF (DISEÑO V3 - CORREGIDO)
# ==========================================
# ==========================================
# FUNCIÓN GENERADORA DE PDF (V4 - TÍTULOS LIMPIOS)
# ==========================================
# ==========================================
# FUNCIÓN GENERADORA DE PDF (V5 - EJES CORREGIDOS)
# ==========================================
# ==========================================
# FUNCIÓN GENERADORA DE PDF (V6 - FINAL PULIDO)
# ==========================================
def create_pdf_report(tickers, start_date, end_date, weights, metrics, var_cvar, fig_frontier, fig_pie):
    """Genera un reporte PDF profesional con todos los gráficos limpios y alineados."""
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter
    
    # --- 1. ENCABEZADO ---
    c.setFillColor(colors.darkblue)
    c.rect(0, height - 80, width, 80, fill=True, stroke=False)
    
    c.setFillColor(colors.white)
    c.setFont("Helvetica-Bold", 24)
    c.drawString(40, height - 50, "AGENCIA DE INVERSIONES")
    c.setFont("Helvetica", 10)
    c.drawString(40, height - 70, f"Reporte de Estrategia Quant | Generado: {date.today()}")

    # --- 2. TEXTO ---
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 14)
    c.drawString(40, height - 110, "1. Perfil de la Estrategia")
    
    c.setFont("Helvetica", 10)
    c.drawString(40, height - 135, f"Objetivo: Maximización de Sharpe Ratio")
    c.drawString(40, height - 150, f"Periodo: {start_date} a {end_date}")
    c.drawString(40, height - 165, f"Activos: {', '.join(tickers)}")

    # --- 3. TABLA Y PASTEL ---
    
    # A. TABLA
    data = [
        ["Métrica", "Estimado", "Nota"],
        ["Retorno Anual", f"{metrics['expected_return']:.2%}", "Proyectado"],
        ["Volatilidad", f"{metrics['volatility']:.2%}", "Anualizada"],
        ["Sharpe Ratio", f"{metrics['sharpe_ratio']:.2f}", "Eficiencia"],
        ["VaR (95%)", f"{var_cvar['var_parametric']:.2%}", "Riesgo Día"],
        ["CVaR (Crisis)", f"{var_cvar['cvar']:.2%}", "Peor Caso"]
    ]
    
    table = Table(data, colWidths=[120, 70, 90])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.darkblue),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
        ('BACKGROUND', (0, 1), (-1, -1), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.grey)
    ]))
    
    table.wrapOn(c, width, height)
    table.drawOn(c, 40, 480) 

    # B. PASTEL
    try:
        c.setFillColor(colors.black)
        c.setFont("Helvetica-Bold", 10)
        c.drawString(380, 610, "Allocation Óptimo (Pesos)")

        fig_pie.update_layout(
            title_text="",
            showlegend=False,
            margin=dict(l=10, r=10, t=10, b=10)
        )
        fig_pie.update_traces(textinfo='label+percent', textposition='inside')

        img_bytes_pie = fig_pie.to_image(format="png", width=250, height=200, scale=2)
        image_pie = io.BytesIO(img_bytes_pie)
        c.drawImage(ImageReader(image_pie), 320, 440, width=220, height=160)
        
    except Exception as e:
        c.drawString(340, 500, "Error gráfico pastel")

    # --- 4. FRONTERA EFICIENTE (CORRECCIÓN FINAL DE LEYENDA) ---
    
# --- 4. FRONTERA EFICIENTE (MODO OSCURO - LEYENDA CORREGIDA) ---
    
 # --- 4. FRONTERA EFICIENTE (AJUSTE FINAL DE LEYENDA) ---
    
    c.setFillColor(colors.black)
    c.setFont("Helvetica-Bold", 12)
    c.drawString(40, 410, "2. Análisis de Frontera Eficiente (Monte Carlo)")
    
    try:
        # AJUSTE: Movemos la leyenda ARRIBA y a la DERECHA
        fig_frontier.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0E1117",
            plot_bgcolor="#0E1117",
            font=dict(color="white"),
            title_text="",
            # 1. Aumentamos el margen superior (t=50) para que quepa la leyenda
            margin=dict(l=60, r=20, t=50, b=60), 
            legend=dict(
                x=1.0,           # Pegado al borde derecho
                y=1.02,          # Justo ENCIMA del gráfico (en el margen)
                xanchor="right", # Alineado a la derecha
                yanchor="bottom", # Anclado desde abajo
                bgcolor="rgba(0,0,0,0)",
                font=dict(color="white"),
                orientation="h"  # (Opcional) Horizontal para que se vea más limpio
            )
        )
        
        img_bytes_frontier = fig_frontier.to_image(format="png", width=700, height=400, scale=2)
        image_frontier = io.BytesIO(img_bytes_frontier)
        c.drawImage(ImageReader(image_frontier), 30, 80, width=550, height=300)
        
    except Exception as e:
        c.setFillColor(colors.red)
        c.drawString(40, 200, f"Error gráfico frontera: {e}")

    # --- 5. FOOTER ---
    c.setFont("Helvetica-Oblique", 8)
    c.setFillColor(colors.gray)
    c.line(40, 50, width-40, 50)
    c.drawString(40, 35, "Documento confidencial generado por IA Portfolio Optimizer.")
    
    c.showPage()
    c.save()
    buffer.seek(0)
    return buffer

    
# Aplicación Streamlit

st.set_page_config(page_title="Optimizador de Portafolios", layout="wide")



st.title('Agencia de Inversiones - Optimizador de Portafolios')



# Sidebar

with st.sidebar:

    st.header("Configuración del Portafolio")

   

    # Input de tickers

    tickers_input = st.text_input(

        "Tickers (separados por comas)",

        value="AAPL, MSFT, GOOG, TSLA",

        help="Ingrese los símbolos de los activos separados por comas"

    )

   

    # Selector de fechas

    col1, col2 = st.columns(2)

    with col1:

        start_date = st.date_input(

            "Fecha de Inicio",

            value=date(2023, 1, 1),

            min_value=date(2000, 1, 1),

            max_value=date.today()

        )

    with col2:

        end_date = st.date_input(

            "Fecha de Fin",

            value=date.today(),

            min_value=date(2000, 1, 1),

            max_value=date.today()

        )

   

    # Botón de optimización

    optimize_button = st.button("Optimizar Portafolio", type="primary", use_container_width=True)



# Procesar cuando se hace click en el botón

if optimize_button:

    # Parsear tickers

    tickers_list = [ticker.strip().upper() for ticker in tickers_input.split(',') if ticker.strip()]

   

    if not tickers_list:

        st.error("Por favor, ingrese al menos un ticker válido.")

    elif start_date >= end_date:

        st.error("La fecha de inicio debe ser anterior a la fecha de fin.")

    else:

        # Mostrar indicador de progreso

        with st.spinner("Procesando datos y ejecutando optimización..."):

            try:

                # Convertir fechas a string

                start_date_str = start_date.strftime('%Y-%m-%d')

                end_date_str = end_date.strftime('%Y-%m-%d')

               

                # Crear instancia del PortfolioManager

                portfolio = PortfolioManager(tickers_list, start_date_str, end_date_str)

               

                # Descargar datos

                portfolio.fetch_data()

               

                # Calcular métricas básicas

                portfolio.calculate_basic_metrics()

               

                # Optimizar para máximo Sharpe Ratio

                sharpe_result = portfolio.optimize_sharpe_ratio()

               

                # Ejecutar simulación de Monte Carlo

                monte_carlo_results = portfolio.simulate_monte_carlo(num_sims=5000)

               

                # Calcular VaR

                var_cvar_results = portfolio.calculate_var_cvar(

                    weights=sharpe_result['weights'],

                    confidence_level=0.95

                )

               

                # Preparar datos para el gráfico

                # Convertir la columna 'Pesos' (que es un array) a string para el gráfico

                monte_carlo_plot = monte_carlo_results.copy()

               

                # Crear gráfico con plotly.express

                fig = px.scatter(

                    monte_carlo_plot,

                    x='Volatilidad',

                    y='Retorno',

                    color='Sharpe',

                    color_continuous_scale='viridis',

                    labels={

                        'Volatilidad': 'Volatilidad (Desviación Estándar Anualizada)',

                        'Retorno': 'Retorno Esperado (Anualizado)',

                        'Sharpe': 'Sharpe Ratio'

                    },

                    title='Simulación de Monte Carlo - Frontera Eficiente',

                    hover_data=['Sharpe']

                )

               

                # Agregar estrella roja grande para el portafolio de Máximo Sharpe

                fig.add_trace(

                    go.Scatter(

                        x=[sharpe_result['volatility']],

                        y=[sharpe_result['expected_return']],

                        mode='markers',

                        marker=dict(

                            symbol='star',

                            size=25,

                            color='red',

                            line=dict(width=2, color='darkred')

                        ),

                        name='Máximo Sharpe Ratio',

                        hovertemplate='<b>Máximo Sharpe Ratio</b><br>' +

                                      'Volatilidad: %{x:.4f}<br>' +

                                      'Retorno: %{y:.4f}<br>' +

                                      'Sharpe: ' + f"{sharpe_result['sharpe_ratio']:.4f}" +

                                      '<extra></extra>'

                    )

                )

               

                # Actualizar layout

                fig.update_layout(

                    height=600,

                    showlegend=True,

                    xaxis_title="Volatilidad",

                    yaxis_title="Retorno Esperado"

                )

               

                # Mostrar gráfico

                st.plotly_chart(fig, use_container_width=True)

               

                # Mostrar métricas en tres columnas

                col1, col2, col3 = st.columns(3)

               

                with col1:

                    st.metric(

                        "Retorno Esperado",

                        f"{sharpe_result['expected_return']*100:.2f}%",

                        delta=f"{sharpe_result['expected_return']:.4f}"

                    )

               

                with col2:

                    st.metric(

                        "Volatilidad",

                        f"{sharpe_result['volatility']*100:.2f}%",

                        delta=f"{sharpe_result['volatility']:.4f}"

                    )

               

                with col3:

                    var_parametric_pct = abs(var_cvar_results['var_parametric']) * 100

                    st.metric(

                        "VaR 95%",

                        f"{var_parametric_pct:.2f}%",

                        delta="Pérdida máxima esperada"

                    )

               

                # Mostrar información adicional en un expander

                with st.expander("Ver detalles del portafolio óptimo"):

                    st.subheader("Pesos del Portafolio")

                    weights_df = pd.DataFrame({

                        'Ticker': portfolio.tickers,

                        'Peso': sharpe_result['weights'],

                        'Porcentaje': sharpe_result['weights'] * 100

                    })

                    st.dataframe(weights_df, use_container_width=True)

                   

                    st.subheader("Métricas Adicionales")

                    st.write(f"**Sharpe Ratio:** {sharpe_result['sharpe_ratio']:.4f}")

                    cvar_pct = abs(var_cvar_results['cvar']) * 100

                    st.write(f"**CVaR 95%:** {cvar_pct:.2f}%")

               # ... (aquí estaba tu código del st.expander)
                    st.write(f"**CVaR 95%:** {cvar_pct:.2f}%")

                # --- PEGA ESTO AQUÍ (DENTRO DEL TRY, ALINEADO CON EL WITH) ---
                
                st.divider() # Línea separadora
                st.subheader("📄 Exportar Reporte para Cliente")
                
                # 1. Necesitamos crear el gráfico de pastel (Pie Chart) para el PDF
                # (Lo creamos aquí rápido porque arriba solo hicimos la tabla)
                weights_df_plot = pd.DataFrame({
                    'Ticker': portfolio.tickers,
                    'Peso': sharpe_result['weights']
                })
                # Solo mostramos los que tienen peso relevante (>0.1%)
                weights_df_plot = weights_df_plot[weights_df_plot['Peso'] > 0.001]
                
                fig_pie = px.pie(
                    weights_df_plot, 
                    values='Peso', 
                    names='Ticker', 
                    title='Allocation Óptimo'
                )

                # 2. Generamos el PDF
                pdf_file = create_pdf_report(
                    tickers_list, 
                    start_date_str, 
                    end_date_str, 
                    sharpe_result['weights'], 
                    sharpe_result, 
                    var_cvar_results, 
                    fig,      # Este es tu gráfico de puntos (Frontera)
                    fig_pie   # Este es el pastel que acabamos de crear
                )
                
                # 3. El Botón
                st.download_button(
                    label="📥 Descargar Reporte PDF (Nivel Agencia)",
                    data=pdf_file,
                    file_name=f"Reporte_Inversion_{date.today()}.pdf",
                    mime="application/pdf"
                )
                # -----------------------------------------------------------


            except Exception as e:

                st.error(f"Error al procesar: {str(e)}")

                st.exception(e)

else:

    # Mensaje inicial

    st.info("👈 Configure los parámetros en la barra lateral y haga clic en 'Optimizar Portafolio' para comenzar.")

   

    # Mostrar información de ayuda

    with st.expander("ℹ️ Información sobre la herramienta"):

        st.markdown("""

        ### Optimizador de Portafolios

       

        Esta herramienta utiliza:

        - **Optimización de Máximo Sharpe Ratio**: Encuentra la combinación óptima de activos que maximiza el retorno ajustado por riesgo.

        - **Simulación de Monte Carlo**: Genera 5,000 escenarios aleatorios para visualizar la frontera eficiente.

        - **Análisis de Riesgo**: Calcula el Value at Risk (VaR) al 95% de confianza.

       

        **Instrucciones:**

        1. Ingrese los tickers de los activos que desea analizar (separados por comas).

        2. Seleccione el rango de fechas para el análisis histórico.

        3. Haga clic en "Optimizar Portafolio" para ejecutar el análisis.

        """)

        