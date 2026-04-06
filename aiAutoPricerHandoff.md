  ---                                                                                                
  Handoff: AI Item Valuation Feature                                                                 
                                                                                                     
  Feature                                                                                          
                                                                                                     
  Automatic AI-powered product identification and pricing for the admin approval queue. When a seller
   submits an item, a background thread sends the item's photos + details to Claude (Sonnet), which  
  web-searches for the product, returns a retail price, suggested resale price, and description.     
  Admins see this pre-loaded in /admin/approve.                                                    

  Spec file
                                                                                                     
  featurefiles/feature_ai_item_valuation.md — full spec with all routes, model, template changes, and
   edge cases.                                                                                       
                                                                                                     
  What's been implemented (all code is written and committed to main)                                
                                                                                                     
  - ItemAIResult model in models.py — status, product_name, retail_price, suggested_price,           
  ai_description, etc.                                                                               
  - Migration migrations/versions/o3p4q5r6s7t8_add_item_ai_result.py — already run locally           
  - anthropic>=0.39.0 added to requirements.txt                                                      
  - run_ai_item_lookup() background function in app.py (~line 770) — builds base64 image content,    
  calls Anthropic API with claude-sonnet-4-20250514 + web_search_20250305 tool, parses JSON, updates 
  ItemAIResult                                                                                       
  - trigger_ai_lookup() helper — creates ItemAIResult with status='pending', then spawns daemon      
  thread                                                                                             
  - Background thread triggers added to both onboard POST and add_item POST — fires after            
  db.session.commit(), never blocks the seller's response                                            
  - Two admin API routes: POST /admin/item/<id>/ai-lookup (re-run) and GET /admin/item/<id>/ai-result
   (poll/fetch JSON)                                                                                 
  - admin_approve.html updated with AI Research Panel (3 states: pending/found/unknown), description 
  side-by-side, "Use this price" / "Use this" buttons, re-run button, JS polling with 60s timeout    
  - CSS added to static/style.css for .ai-panel, .description-columns, etc.                          
  - .env created locally with SECRET_KEY and ANTHROPIC_API_KEY                                       
  - Test suite: 123 passed, 6 failed (all pre-existing, none AI-related)                             
                                                                                                     
  Current bug                                                                                        
                                                                                                     
  The AI lookup completes but returns status = 'unknown' (could not identify product) even for a     
  clear, branded item photo. The lookup runs, doesn't crash, but Claude isn't successfully           
  identifying the product. This means either:                                                        
  1. The photos aren't being sent correctly (base64 encoding, media type, or the images are too      
  processed/compressed)                                                                              
  2. The web search tool isn't being invoked properly (tool config format may be wrong)              
  3. The response parsing is stripping/mangling the result (code fence stripping, JSON extraction    
  from a response that includes tool-use blocks)                                                     
  4. Claude's text response is embedded in tool-result content blocks rather than a top-level text   
  block, so raw_text ends up empty                                                                   
                                                                                                     
  What hasn't been tried yet                                                                         
                                                                                                     
  - Check raw_response on the ItemAIResult record in the database — this stores whatever text was    
  extracted from Claude's response and will reveal whether the API returned anything useful          
  - Check server logs for the background thread — any exceptions or the actual API response shape    
  - Inspect the response content blocks — with web search enabled, Claude returns tool_use,          
  server_tool_use, and text blocks; the current code only looks for .text attribute which may miss   
  the actual answer                                                                                  
  - Test the API call in isolation (e.g., a standalone Python script) to confirm the model + web     
  search tool config works                                                                           
                                                                                                     
  Next step                                                                                          
                                                                                                     
  Check the ItemAIResult.raw_response field in the database for the test item to see what Claude     
  actually returned. That will tell you whether the problem is on the API call side or the response  
  parsing side. Run in flask shell:                                                                  
  from models import ItemAIResult                                                                  
  r = ItemAIResult.query.order_by(ItemAIResult.id.desc()).first()
  print(r.status, r.raw_response)                                
                                                                                                     
  Key files to read first in the new session                                                         
                                                                                                     
  1. featurefiles/feature_ai_item_valuation.md — the spec                                            
  2. CODEBASE.md — full codebase reference                                                           
  3. app.py ~line 770–920 — the AI lookup function and trigger helper                                
                                                                                                     
  ---  