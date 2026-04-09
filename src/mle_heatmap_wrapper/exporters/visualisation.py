import pandas as pd
import plotly.express as px

def plot_radius_heatmap(
    df,
    cr_to_mm,
    radius_col="radius",
    section_col="section",
    value_col="value",
    color_scale="RdBu_r",
    title="Radius vs Distance Heatmap"
):
    """
    Plot interactive heatmap with physical mm aspect ratio.

    radius column is assumed to be percentage of nominal_radius_mm.
    """

    data = df.copy()

    # convert CR -> mm
    data["distance_mm"] = data[section_col].map(cr_to_mm)

    if data[radius_col].dtype == "object":
        data[radius_col] = (
            data[radius_col]
            .astype(str)
            .str.replace("R", "", regex=False)
            .astype(float)
        )

    # pivot
    pivot = data.pivot(
        index=radius_col,
        columns="distance_mm",
        values=value_col
    ).sort_index()

    fig = px.imshow(
        pivot,
        aspect="auto",  # we'll control ratio manually
        origin="lower",
        color_continuous_scale=color_scale
    )

    # enforce physical aspect ratio (1mm = 1mm)
    fig.update_layout(
        title=title,
        template="plotly_white",
        xaxis_title="Distance (mm)",
        yaxis_title="Radius (mm)",
        font=dict(size=14),
        title_x=0.5,
    )

    fig.update_yaxes(
        scaleanchor="x",
        scaleratio=1
    )

    fig.update_coloraxes(colorbar_title=value_col)

    return fig