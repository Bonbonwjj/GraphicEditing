# Chart-type rule reference

Read exact values from the supplied style profile. This table helps match templates; it is not a list of accepted upload types and never authorizes changing chart type.

| Chart | Normalize when the template matches | Preserve or request an explicit project rule for |
|---|---|---|
| Box | Centers, width, gap, outline, median, whisker and cap widths, fill, existing significance bracket | Quantiles, whisker extent, outliers, data grouping |
| Bar | Width, within/between-group gaps, outline, fill, existing legend | Heights, errors, zero baseline, grouped versus stacked meaning |
| Line | Line `3.2 pt`, markers, error bars and caps; add missing error bars from explicitly defined error columns or a justified aggregate conversion, e.g. supplied SD and n to explicitly requested SEM | x/y values, connection order, missing-value treatment, existing error type and values |
| Scatter | Point shape, area, alpha, outline, and any existing fit-line appearance; never create a missing fit during normalization | Coordinates, fit presence, existing model and coefficients |
| Mean with error | Point and error-bar appearance, cap, group positions | Mean/error values and whether errors are SEM, SD, or CI |
| Violin | Body center, width, gap, outline, fill; q25/median/q75 lines and q25–q75 connector for a matching template with stored quartiles or original plotting observations; median line twice outer-line length | Existing internal layers, density shape, bandwidth, truncation, unavailable stored quartiles/plotting observations |
| Histogram | Existing bar outline, color, alpha, visual gap, labels | Bin count/edges and count versus density |
| Heatmap | Closed frame tight to matrix; cell borders; category ticks; colorbar right and equal to the rendered matrix height; significance marks centered in their own cells, including off-diagonal cells; no ordinary x-axis downward offset | Matrix values and order, comparison/test/p-value source, color limits, normalization |
| Composite | Normalize each existing box, point, connector, line, and error bar; avoid legend overlap | Artist layering, paired links, twin-axis mapping, scientific meaning |

Example previews do not authorize an overlay. The stored CSV must meet the missing-error-bar requirements in `SKILL.md`; otherwise keep the original chart and report why error bars could not be added. An absent scatter fit is not a normalization failure. For a multi-panel chart without a configured panel template, retain its grid and panel layout and apply safe common or existing-artist rules only.

For two charts using the same matched template and profile version, compare fixed figure properties and rendered dimensions. Tick numbers, labels, and data geometry may differ. For unsupported types, report the missing style parameters rather than replacing the chart.
