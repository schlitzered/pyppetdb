# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

pyppetdb is a Python replacement for PuppetDB, providing a modern implementation that maintains compatibility with Puppet's infrastructure while adding new capabilities. The project uses FastAPI for the web framework, MongoDB as the primary database, and implements various Puppet-specific features including catalog management, node reporting, Hiera integration, and Certificate Authority (CA) functionality.

## Repository Structure

- `pyppetdb/` - Main application codebase
  - `main.py` - Entry point and FastAPI application setup
  - `controller/` - API controllers organizing routes by function
  - `crud/` - Data access layer with MongoDB operations
  - `model/` - Pydantic models for data validation
  - `ca/` - Certificate Authority implementation
  - `config.py` - Configuration using Pydantic Settings
  - `container.py` - Dependency injection container
- `tests/` - Unit and integration tests
- `docs/` - Documentation files

## Key Features

### Core Functionality
- **PuppetDB Compatibility**: Implements PuppetDB API endpoints for compatibility with existing tools
- **Catalog Management**: Stores, retrieves, and manages Puppet catalogs
- **Node Reporting**: Processes and stores node reports and events
- **Hiera Integration**: Supports Hiera data lookup and configuration
- **Certificate Authority**: Manages CA operations including certificate signing and CRLs

### Architecture Components

1. **Dependency Injection Container** (`container.py`): Centralized service management
2. **Data Access Layer** (`crud/`): MongoDB operations with common CRUD patterns, migrations, and indexing
3. **API Controllers** (`controller/`): Route organization for different API groups:
   - Management API (`/api`)
   - PuppetDB Proxy (`/pdb`)  
   - Puppet Proxy (`/puppet`)
4. **Configuration System** (`config.py`): Pydantic-based settings with environment variable support
5. **Certificate Authority Module** (`ca/`): CA signing, certificate management, and CRL handling

## Development Setup

### Prerequisites
- Python 3.12+
- MongoDB instance (local or remote)
- Required packages in `requirements.txt`

### Running Tests
```bash
# Run all tests
python -m unittest discover tests/

# Run specific test file
python -m unittest tests/unit/test_crud_common.py

# Run with coverage
coverage run -m unittest discover tests/
coverage report
```

### Running the Application
```bash
# Create a .env file with required configuration
echo "app_secretkey=your-secret-key-here" > .env

# Start the server
python pyppetdb/main.py

# With auto-reload during development
python pyppetdb/main.py --reload
```

### Common Commands
- `python -m unittest discover tests/` - Run all unit tests
- `python pyppetdb/main.py --help` - Show CLI options
- `python pyppetdb/main.py create-admin` - Create an admin user
- `python pyppetdb/main.py init-ca` - Initialize default Puppet CA

## Codebase Patterns

### CRUD Operations
The application uses a standardized CRUD pattern in the `pyppetdb/crud/` directory:
- All CRUD classes inherit from `CrudMongo`
- Schema validation is implemented using Pydantic models with MongoDB JSON schema validation
- Migrations are supported through versioned schema changes
- Index management is handled automatically with version control

### Configuration
Configuration uses Pydantic Settings with environment variable mapping:
- Nested configuration properties use `_` as delimiter (e.g., `app_main_port`)
- List values are provided as JSON strings
- Required fields have no defaults and must be set in `.env`

### API Structure
The application organizes routes into different controllers:
1. **Management API** (`/api`) - Main application APIs
2. **PuppetDB Proxy** (`/pdb`) - PuppetDB compatibility layer  
3. **Puppet Proxy** (`/puppet`) - Puppet server proxy functionality
4. **OAuth** (`/oauth`) - Authentication endpoints

### Certificate Authority
The CA system includes:
- Authority management (`CrudCAAuthorities`)
- Space management (`CrudCASpaces`) 
- Certificate handling (`CrudCACertificates`)
- CRL refresh worker
- Certificate signing and validation

## Testing Strategy

The codebase uses unittest with a focus on:
- Unit testing individual components and their behavior
- Integration testing through the full CRUD pipeline
- Mocking external dependencies (database, HTTP clients)
- Testing both success and error conditions

Tests are located in `tests/unit/` and follow the naming convention `test_<module_name>.py`.

## Configuration Reference

The application is configured via environment variables or a `.env` file. Key configuration sections include:
- Global settings (`app_`)
- Management API (`app_main_`)
- Puppet proxy (`app_puppet_`)
- PuppetDB proxy (`app_puppetdb_`)
- Certificate Authority (`ca_`)
- Jobs (`jobs_`)
- MongoDB (`mongodb_`)
- LDAP (`ldap_`)
- OAuth providers (`oauth_<name>_`)

See `docs/configuration_reference.md` for detailed documentation.