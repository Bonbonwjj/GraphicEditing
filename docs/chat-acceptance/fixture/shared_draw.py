def draw_series(ax, data, group, color):
    rows = data[data['group'] == group]
    return ax.plot(rows['x'], rows['mean'], label=group, color=color, linewidth=1.5, marker='o')
