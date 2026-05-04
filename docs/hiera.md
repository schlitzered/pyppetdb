# Hiera

Hiera is PyppetDB's hierarchical key/value lookup system. It is designed to separate configuration data from application logic, allowing for flexible, fact-based configuration management across large-scale environments.

## How Hiera Works

Hiera organizes data into a hierarchy of **Levels**. When you perform a **Lookup** for a specific **Key**, Hiera evaluates the hierarchy based on the **Facts** provided in the request.

By defining levels with placeholders like `env_{environment}`, you can target data specifically to nodes based on their attributes. Hiera will traverse the hierarchy, and if merging is enabled, combine data from multiple levels, with higher-priority levels overriding lower ones.

## Models: Static and Dynamic

Models define the structure and validation rules for Hiera data. Both types use **Pydantic** under the hood, ensuring that all data stored in Hiera is consistent and valid.

### Dynamic Models
Dynamic models can be created and managed entirely via the API without writing any Python code. They use a simplified JSON schema-like structure to define the expected data format.

*   **Pros:** Easy to create on-the-fly via API; no deployment or restart required.
*   **Cons:** Limited to standard JSON schema validation; cannot handle complex custom validation logic.

### Static Models
Static models are defined in Python code as part of a plugin. They use full Pydantic models, allowing for complex validation rules, cross-field checks, and custom types.

*   **Pros:** Full power of Python and Pydantic; ideal for complex configurations requiring strict validation.
*   **Cons:** Requires writing code and deploying the plugin; requires a service restart to register new models.

!!! note "Example Plugin"
    You can find an example of a static model plugin in the `pyppetdb_dummy_plugin` directory of the repository.

## Keys

A **Key** is a root-level attribute in Hiera (e.g., `ntp_servers`). Every key is associated with a **Model** (either static or dynamic). 

*   The model validates all data assigned to that key across all levels.
*   You can change a key's model later. However, PyppetDB will perform a "dry-run" validation of all existing data against the new model. If any existing data is incompatible with the new model, the change will be rejected to prevent data corruption.

## Levels

**Levels** define the hierarchy. Each level has a **Priority** (higher numbers indicate higher priority).

Levels often use fact placeholders in their ID, such as `env_{environment}` or `role_{role}`. This allows the same level definition to serve different data depending on the node's facts.

!!! warning "URL Encoding"
    When using tools like `curl` to manage levels with placeholders (containing `{` or `}`), you should use the `-g` (`--globoff`) flag to prevent the tool from interpreting the braces as globbing patterns.

## Level Data

**Level Data** is the actual value assigned to a Key at a specific Level. 

When adding data to a level that contains placeholders, you must provide the values for those facts. The `data_id` in the API path must match the **expanded** version of the `level_id`. For example, if the level is `env_{environment}` and the fact is `environment:production`, the `data_id` must be `env_production`.

## Lookup

The lookup process resolves the value of a key for a specific context.

1.  **Facts**: You must provide all facts necessary to satisfy the hierarchy. If a level in the hierarchy requires a fact that isn't provided, the lookup will fail with a validation error.
2.  **Merging**:
    *   **Merge Disabled (default)**: Returns the value from the highest-priority level that contains data for the key.
    *   **Merge Enabled**: Merges dictionaries and lists across all matching levels. Values from higher-priority levels override those from lower ones.

---

## API Examples

### Setup
Set your credentials as environment variables for the examples below:
```bash
export API_URL="http://localhost:3000/api/v1"
export SECRET_HEADER="x-secret-id: <your_secret_id>"
export TOKEN_HEADER="x-secret: <your_secret>"
```

### 1. Managing Models

**Create a Simple Dynamic Model (Boolean):**
```bash
curl -s -X POST "$API_URL/hiera/key_models/dynamic/dynamic:bool_model" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{
           "description": "A simple boolean toggle",
           "model": {
             "title": "BoolModel",
             "type": "object",
             "required": ["data"],
             "properties": {
               "data": { "type": "boolean" }
             }
           }
         }'
```

**Create a Complex Dynamic Model (Object):**
```bash
curl -s -X POST "$API_URL/hiera/key_models/dynamic/dynamic:network_model" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{
           "description": "Network configuration",
           "model": {
             "title": "NetworkModel",
             "type": "object",
             "required": ["data"],
             "properties": {
               "data": {
                 "type": "object",
                 "properties": {
                   "ip": { "type": "string" },
                   "mtu": { "type": "integer" }
                 },
                 "required": ["ip"]
               }
             }
           }
         }'
```

### 2. Managing Keys

**Create a Key associated with a Dynamic Model:**
```bash
curl -s -X POST "$API_URL/hiera/keys/my_feature_flag" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{
           "key_model_id": "dynamic:bool_model", 
           "description": "Toggle for the new feature"
         }'
```

### 3. Managing Levels

**Create a Global Level (Priority 0):**
```bash
curl -s -X POST "$API_URL/hiera/levels/common" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{"priority": 0, "description": "Global defaults"}'
```

**Create a Fact-Based Level (Priority 50):**
```bash
# Note the use of -g for literal braces in the URL
curl -s -g -X POST "$API_URL/hiera/levels/env_{environment}" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{"priority": 50, "description": "Environment-specific overrides"}'
```

### 4. Managing Level Data

**Add Default Data (to 'common' level):**
```bash
curl -s -X POST "$API_URL/hiera/data/common/common/my_feature_flag" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{
           "facts": {},
           "data": false
         }'
```

**Add Override Data (to 'env_{environment}' level for 'production'):**
```bash
# Level: env_{environment}, Fact environment=production -> data_id: env_production
curl -s -g -X POST "$API_URL/hiera/data/env_{environment}/env_production/my_feature_flag" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" -H "Content-Type: application/json" \
     -d '{
           "facts": {"environment": "production"},
           "data": true
         }'
```

### 5. Performing Lookups

**Lookup with facts (satisfying both 'common' and 'env_{environment}'):**
```bash
curl -s -g -G "$API_URL/hiera/lookup/my_feature_flag" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" \
     --data-urlencode "fact=environment:production"
# Returns: {"data": true}
```

**Lookup with merging enabled:**
```bash
curl -s -g -G "$API_URL/hiera/lookup/some_dict_key?merge=true" \
     -H "$SECRET_HEADER" -H "$TOKEN_HEADER" \
     --data-urlencode "fact=environment:production"
```
