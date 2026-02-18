# Project Context
We are building a feature for "Campus Swap," a college student marketplace. We have a black-and-white sketch of a dorm room (image.png) featuring various items (mini-fridge, bed, microwave, etc.). 

# Goal
Create an interactive HTML/CSS/JS component where the user can hover over items in the static image to see their potential resale value, and click them to add them to a dynamic "receipt" below the image.

# Technical Requirements

## 1. The Interactive Image Map (SVG Overlay)
- Create an image container with `position: relative`.
- Place the static image (`image.png`) inside as the base layer.
- Overlay an inline `<svg>` element perfectly scaled to match the image dimensions.
- Inside the SVG, create placeholder `<polygon>` elements for the following items: Minifridge, Bed, Headboard, Rug, Microwave, Couch, TV, AC Unit. *(Note: Generate dummy coordinate points for these polygons; I will map the exact coordinates later).*
- Default state for polygons: `fill: transparent`.
- Hover state for polygons: Fill with "Campus Swap Green" (use hex `#00FF00` as a placeholder, I will adjust to our brand color) with a slight opacity (e.g., `0.4`) so the sketch beneath remains visible.

## 2. The Hover Tooltip
- Create a floating `div` for a tooltip positioned near the top of the image container.
- When hovering over an SVG polygon, use JavaScript to update the tooltip text (e.g., "Minifridge: + $50") and make it visible. 
- The tooltip should fade out when not hovering over an interactive item.

## 3. The Dynamic Receipt
- Below the image container, build a "Receipt" UI section.
- When a user clicks an SVG polygon, append that item and its corresponding dollar value to the receipt list.
- If an item is already on the receipt, clicking it again on the image should remove it (toggle functionality).
- Keep a running "Total Potential Earnings" tally at the bottom of the receipt, rendered in Campus Swap Green.

## Code Structure
Provide the solution using standard HTML, CSS, and Vanilla JavaScript so it can be easily integrated into a Flask Jinja2 template. Keep the styling clean, modern, and mobile-responsive.