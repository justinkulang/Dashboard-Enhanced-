# Mikrotik Hotspot User Management Dashboard

This project provides a web-based dashboard for managing users on one or more Mikrotik Hotspot routers. It includes features for user creation, batch generation, profile management, activity monitoring, and more, all from a single interface. It incorporates security best practices like session management, CSRF protection, and guidance for production deployment.

## Features

*   **Multi-Router Support:** Manage multiple Mikrotik devices from one dashboard.
*   **User Management:** Create, edit, delete, and view hotspot users on the active router.
*   **Batch User Creation:** Generate multiple voucher-style users at once on the active router.
*   **Profile Management:** Manage hotspot user profiles from the active Mikrotik router.
*   **Active Sessions:** View and disconnect active hotspot users on the active router.
*   **Voucher Generation:** Export user batches as printable HTML or PDF vouchers with QR codes.
*   **Analytics:** Basic analytics on data usage by profile and top users for the active router.
*   **Secure Access:**
    *   Web application login system using Flask-Login (session-based).
    *   CSRF protection for all state-changing operations using Flask-WTF.
*   **Internationalization (i18n):** Support for multiple languages (English, Arabic, French).
*   **Configurable:** Key settings, including router configurations, managed via `config.json` and the application UI.
*   **Production Ready:** Includes Gunicorn configuration and guidance for HTTPS setup.

## Prerequisites

*   Python 3.7+
*   pip (Python package installer)
*   One or more Mikrotik routers with the API service enabled.
*   Network connectivity between the server running this application and your Mikrotik router(s).
*   (Optional, for PDF export) System dependencies for WeasyPrint (see WeasyPrint documentation for your OS).

## Setup and Installation

1.  **Clone Repository:**
    ```bash
    git clone <repository_url>
    cd <repository_directory>
    ```

2.  **Create Virtual Environment (Recommended):**
    ```bash
    python -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  **Install Dependencies:**
    ```bash
    pip install -r requirements.txt
    ```
    The `requirements.txt` file contains pinned versions for stable builds. You can update these or generate your own environment's specific versions using `pip freeze > requirements.txt` after testing.

4.  **Initial Configuration (`config.json`):**
    *   Upon first run, or if `config.json` is missing, a default configuration file will be created.
    *   **Web Application Admin:**
        *   A default admin user for the web dashboard is created with credentials:
            *   Username: `admin`
            *   Password: `changeme`
        *   **IMPORTANT:** Change this default password immediately after the first login! You can generate a new password hash using Python and Werkzeug security:
            ```python
            from werkzeug.security import generate_password_hash
            new_hash = generate_password_hash('your_new_strong_password')
            print(new_hash)
            ```
            Then, update the `password_hash` value in the `app_admin` section of `config.json` with this new hash.
    *   **Router Configuration:**
        *   The application now supports managing multiple Mikrotik routers.
        *   Upon first run, `config.json` is created with a placeholder for a default router.
        *   Router configurations (including adding new routers, editing existing ones, and selecting the active router for operations) are managed through the **"Routers" tab** in the web application's interface after logging in.
        *   The `config.json` file will store an array of router configurations under the `routers` key and an `active_router_id` key indicating the currently selected router.
        *   Example structure for a router entry within the `routers` array:
            ```json
            {
              "id": "unique-router-id", // Automatically generated
              "name": "My Office Router",
              "host": "192.168.88.1",
              "port": 8728,
              "username": "admin_api_user",
              "password": "api_password",
              "use_ssl": false,
              "hotspot_login_url": "http://hotspot.example.com/login"
            }
            ```
    *   **Log File Location:** The default log file is `mikrotik_dashboard.log`. You can change this in `config.json` under `server.log_file`.

## Managing Routers

Once logged into the web application, you will typically find options to:
*   **List configured routers.**
*   **Add a new router:** Provide a name, host IP/domain, API port, API username, and password.
*   **Edit an existing router's details.**
*   **Delete a router configuration.**
*   **Set a router as active:** Operations like viewing users, profiles, active sessions, or creating new users/vouchers will apply to the currently active router.

## Running the Application

### Development

For development purposes, you can use the Flask development server:
```bash
python app.py
```
This server is convenient but not suitable for production. The debug mode is sourced from `config.json` (`server.debug`), which now defaults to `false`.

### Production (Recommended)

For production, it is highly recommended to use a production-grade WSGI server like Gunicorn, and to run the application behind a reverse proxy like Nginx for HTTPS termination and serving static files.

1.  **Using Gunicorn:**
    A `gunicorn_config.py` file is provided. It attempts to load server host and port from `config.json`.
    Run Gunicorn with:
    ```bash
    gunicorn --config gunicorn_config.py app:app
    ```
    Ensure Gunicorn is installed (`pip install gunicorn`).

2.  **Further Production Setup:**
    Refer to the "Production Deployment" section below for crucial details on HTTPS, environment variables, etc.

## Production Deployment

When deploying this application to a production environment, several considerations should be taken into account for security, reliability, and performance.

### Environment Variables for Configuration (Recommended for Production)

For enhanced security and flexibility, especially in production, it's **highly recommended** to configure sensitive settings using environment variables. These take precedence over values defined in `config.json`.

*   **`FLASK_SECRET_KEY` (Critical):** For session security.
    *   Set this to a strong, unique, and random string.
    *   Example: `export FLASK_SECRET_KEY='your_very_strong_random_secret_key'`
*   **Application Admin Credentials:**
    *   `APP_ADMIN_USERNAME`: The username for the web dashboard admin. (Defaults to `admin` from `config.json` if not set).
    *   `APP_ADMIN_PASSWORD_HASH`: The Werkzeug-compatible password hash for the web dashboard admin.
        *   Generate this hash using the provided `passwordg_generator.py` script or by running `python -c "from werkzeug.security import generate_password_hash; print(generate_password_hash('your_password'))"`.
        *   Example: `export APP_ADMIN_PASSWORD_HASH='your_generated_werkzeug_hash'`
        *   **Note:** If `APP_ADMIN_PASSWORD_HASH` is set as an environment variable, the in-app password change feature will be disabled for the admin user. Password changes must then be made by updating this environment variable and restarting the application. If this environment variable is not set, the password hash is managed via `config.json`, and the in-app password change feature (accessible in the Settings tab) can be used.
*   **Router Configuration via Environment Variables:**
    *   With the introduction of multi-router support, managing individual router connection details (like host, port, username, password) via environment variables becomes more complex (e.g., requiring prefixed variables like `ROUTER_0_HOST`, `ROUTER_1_HOST`).
    *   Currently, the application prioritizes router configurations stored in `config.json` (managed via the UI). The global `MIKROTIK_HOST`, `MIKROTIK_PASSWORD`, etc., environment variables are **no longer the primary way** to configure router connections for multi-router setups.
    *   It's recommended to manage router connection details through the application's web interface or by directly editing the `routers` array in the `config.json` file.
*   **Server Settings (Optional Overrides):**
    *   `SERVER_HOST`: Host for the web application to bind to (e.g., `0.0.0.0` or `127.0.0.1`).
    *   `SERVER_PORT`: Port for the web application.
    *   `FLASK_DEBUG`: Set to `true` or `false` to enable/disable Flask debug mode. Overrides `server.debug` in `config.json`.
    *   `APP_ENV`: If set to `production`, Flask debug mode will be forced to `false`.

If these environment variables are not set, the application will fall back to using the values from `config.json`. However, for production, relying on environment variables for secrets like `FLASK_SECRET_KEY`, `APP_ADMIN_PASSWORD_HASH`, and `MIKROTIK_PASSWORD` is strongly advised. The application will log warnings if it loads these sensitive values from `config.json` when not in debug mode.

### `config.json` File
The `config.json` file is still used for default values and for settings not typically managed by environment variables (like log file paths or specific feature flags if any are added later). Upon first run, if `config.json` is missing, a default version will be created.

### Debug Mode
*   **Action Required:** Ensure that Flask debug mode is `false` in production. This can be achieved by:
    1.  Setting `server.debug` to `false` in `config.json`.
    2.  Setting the `FLASK_DEBUG` environment variable to `false`.
    3.  Setting the `APP_ENV` environment variable to `production`.
*   The application defaults `server.debug` to `false` if the key is missing in `config.json` or if a new config file is generated.
*   Running with `FLASK_DEBUG=true` or `server.debug=true` in production exposes security risks (like the Werkzeug debugger) and should be avoided.

### WSGI Server (Gunicorn)
*   The provided `gunicorn_config.py` sets up Gunicorn to bind to the host and port specified in `config.json` (defaulting to `0.0.0.0:5000`).
*   It also sets a recommended number of worker processes.
*   You can customize `gunicorn_config.py` further for advanced Gunicorn settings (e.g., logging, timeouts).

### HTTPS Setup (Recommended)
For production, it is strongly recommended to serve the application over HTTPS. The typical setup involves running Gunicorn locally and using a reverse proxy like Nginx or Apache in front of it to handle HTTPS termination.

**Why HTTPS is Crucial:**
*   **Security:** Encrypts data between the user's browser and the server.
*   **Data Integrity:** Ensures data is not tampered with during transit.
*   **User Trust:** Browsers mark HTTP sites as "not secure."

**Example Nginx Configuration:**
(This example assumes Gunicorn is listening on `127.0.0.1:5000`)

```nginx
server {
    listen 80;
    server_name your_domain.com; # Replace with your actual domain

    # Redirect all HTTP traffic to HTTPS
    location / {
        return 301 https://$host$request_uri;
    }
}

server {
    listen 443 ssl http2;
    server_name your_domain.com; # Replace with your actual domain

    # SSL Certificate paths
    ssl_certificate /etc/letsencrypt/live/your_domain.com/fullchain.pem; # Adjust path (e.g., from Let's Encrypt)
    ssl_certificate_key /etc/letsencrypt/live/your_domain.com/privkey.pem; # Adjust path
    
    # Recommended SSL settings (consult current best practices)
    # ssl_protocols TLSv1.2 TLSv1.3;
    # ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
    # ssl_prefer_server_ciphers off;
    # Add HSTS header (optional, but recommended)
    # add_header Strict-Transport-Security "max-age=63072000; includeSubDomains; preload" always;

    # (Optional) Serve static files directly with Nginx for better performance
    # location /static {
    #     alias /path/to/your/project/static; # Adjust to your app's static folder
    #     expires 7d;
    #     access_log off;
    # }

    location / {
        proxy_pass http://127.0.0.1:5000; # Must match Gunicorn's bind address
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
**Notes for Nginx:**
*   Replace `your_domain.com` with your domain.
*   Adjust SSL certificate paths. Consider using Certbot from Let's Encrypt for free certificates.
*   Ensure Gunicorn (via `gunicorn_config.py` and `config.json`) binds to `127.0.0.1:5000` if Nginx is on the same machine. If Gunicorn binds to `0.0.0.0`, ensure your firewall is configured appropriately.

### Logging
*   The application is configured to log to both the console and a file.
*   The default log file is `mikrotik_dashboard.log` (configurable in `config.json` via `server.log_file`).
*   Console and file log levels are also configurable in `config.json` (`server.log_level_console`, `server.log_level_file`).
*   When using Gunicorn, its own logging mechanisms (e.g., `accesslog`, `errorlog` in `gunicorn_config.py`) can also be used to capture stdout/stderr from the application.

### Pinned Dependencies
*   `requirements.txt` includes pinned versions for all dependencies to ensure stable and reproducible builds.
*   If you modify your environment or update packages, it's good practice to regenerate this file with your current working set: `pip freeze > requirements.txt`.

### Other Production Considerations (from previous README section)
*   **Database:** For more robust data storage than `config.json` (especially for user credentials if not using a fixed admin user), consider using a proper database system.
*   **Backups:** Implement regular backups of your application data and configurations.
*   **Monitoring:** Set up monitoring for your application and server to track performance and errors.
*   **Firewall:** Configure a firewall to only allow necessary traffic to your server (e.g., ports 80 and 443).

## Translations (i18n)

This application uses Flask-Babel for internationalization.
*   Supported languages: English (default), Arabic, French.
*   Translations are stored in the `translations` directory.
*   To add or update translations:
    1.  Extract messages: `pybabel extract -F babel.cfg -o messages.pot .`
    2.  Initialize a new language (e.g., for Spanish 'es'): `pybabel init -i messages.pot -d translations -l es`
    3.  Update existing languages: `pybabel update -i messages.pot -d translations`
    4.  Compile translations: `pybabel compile -d translations`
    (Ensure you have Babel installed and `babel.cfg` correctly configured if you modify translatable files.)

*(License section would go here if applicable)*
*(Contributing guidelines would go here if applicable)*
