/**
 * API client for JupySQL server extension.
 *
 * Provides methods to communicate with the REST API endpoints
 * defined in src/sql/labextension/handlers.py
 */

import { URLExt } from '@jupyterlab/coreutils';
import { ServerConnection } from '@jupyterlab/services';

/**
 * Connection information returned by the API
 */
export interface IConnection {
  key: string;
  url: string;
  alias: string | null;
  is_current: boolean;
}

/**
 * Schema information
 */
export interface ISchema {
  name: string;
  is_default: boolean;
}

/**
 * Table information
 */
export interface ITable {
  name: string;
}

/**
 * Column information
 */
export interface IColumn {
  name: string;
  type: string;
}

/**
 * Kernel information
 */
export interface IKernel {
  id: string;
  name: string;
  path: string;
}

/**
 * Table preview data
 */
export interface ITablePreview {
  data: any[][];
  columns: string[];
  offset: number;
  limit: number;
}

/**
 * API response for connection operations
 */
export interface IConnectionResponse {
  status: string;
  message?: string;
  connection_key?: string;
  connection_label?: string;
}

/**
 * API client class for JupySQL operations
 */
export class JupySQLAPI {
  private serverSettings: ServerConnection.ISettings;
  private baseUrl: string;

  constructor() {
    this.serverSettings = ServerConnection.makeSettings();
    this.baseUrl = URLExt.join(this.serverSettings.baseUrl, 'jupysql');
  }

  /**
   * Make a GET request to the API
   */
  private async get<T>(endpoint: string, params?: Record<string, string>): Promise<T> {
    let url = URLExt.join(this.baseUrl, endpoint);

    // Add query parameters if provided
    if (params) {
      const searchParams = new URLSearchParams(params);
      url = `${url}?${searchParams.toString()}`;
    }

    const response = await ServerConnection.makeRequest(
      url,
      { method: 'GET' },
      this.serverSettings
    );

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || `API request failed: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Make a DELETE request to the API
   */
  private async delete<T>(endpoint: string, body: any): Promise<T> {
    const url = URLExt.join(this.baseUrl, endpoint);
    const response = await ServerConnection.makeRequest(
      url,
      { method: 'DELETE', body: JSON.stringify(body) },
      this.serverSettings
    );
    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || `API request failed: ${response.statusText}`);
    }
    return response.json();
  }

  /**
   * Make a POST request to the API
   */
  private async post<T>(endpoint: string, body: any): Promise<T> {
    const url = URLExt.join(this.baseUrl, endpoint);

    const response = await ServerConnection.makeRequest(
      url,
      {
        method: 'POST',
        body: JSON.stringify(body),
      },
      this.serverSettings
    );

    if (!response.ok) {
      const data = await response.json();
      throw new Error(data.error || `API request failed: ${response.statusText}`);
    }

    return response.json();
  }

  /**
   * Get database connections, optionally filtered to a specific kernel.
   * If kernelId is provided, only connections from that kernel are returned.
   * Otherwise, connections from all kernels are aggregated and deduplicated.
   */
  async getConnections(kernelId?: string): Promise<IConnection[]> {
    const params: Record<string, string> = {};
    if (kernelId) {
      params.kernel_id = kernelId;
    }
    const response = await this.get<{ connections: IConnection[] }>('connections', params);
    return response.connections;
  }

  /**
   * Ensure the JupySQL (%sql) magic extension is loaded in all running kernels.
   * Called automatically when the sidebar panel mounts so that users don't need
   * to run %load_ext sql manually before browsing connections.
   */
  async initExtension(): Promise<{ status: string; note?: string }> {
    return this.post<{ status: string; note?: string }>('init', {});
  }

  /**
   * Add a new database connection by executing %sql in the kernel.
   * If allKernels is true, the connection is added to ALL running kernels.
   */
  async addConnection(
    connectionString: string,
    alias?: string,
    allKernels?: boolean
  ): Promise<IConnectionResponse> {
    return this.post<IConnectionResponse>('connections', {
      connection_string: connectionString,
      alias,
      all_kernels: allKernels ?? false,
    });
  }

  /**
   * Get schemas for a connection
   */
  async getSchemas(connectionKey: string): Promise<ISchema[]> {
    const response = await this.get<{ schemas: ISchema[] }>('schemas', {
      connection_key: connectionKey,
    });
    return response.schemas;
  }

  /**
   * Get tables for a schema
   */
  async getTables(connectionKey: string, schema: string | null): Promise<ITable[]> {
    const params: Record<string, string> = {
      connection_key: connectionKey,
    };

    if (schema) {
      params.schema = schema;
    }

    const response = await this.get<{ tables: ITable[] }>('tables', params);
    return response.tables;
  }

  /**
   * Get columns for a table
   */
  async getColumns(
    connectionKey: string,
    table: string,
    schema: string | null
  ): Promise<IColumn[]> {
    const params: Record<string, string> = {
      connection_key: connectionKey,
      table,
    };

    if (schema) {
      params.schema = schema;
    }

    const response = await this.get<{ columns: IColumn[] }>('columns', params);
    return response.columns;
  }

  /**
   * Get preview data for a table
   */
  async getTablePreview(
    connectionKey: string,
    table: string,
    schema: string | null,
    limit: number = 100,
    offset: number = 0
  ): Promise<ITablePreview> {
    const params: Record<string, string> = {
      connection_key: connectionKey,
      table,
      limit: limit.toString(),
      offset: offset.toString(),
    };

    if (schema) {
      params.schema = schema;
    }

    return this.get<ITablePreview>('preview', params);
  }

  /**
   * Delete (close and remove) a connection in all running kernels.
   */
  async deleteConnection(connectionKey: string): Promise<{ status: string }> {
    return this.delete<{ status: string }>('connections', {
      connection_key: connectionKey,
    });
  }

  /**
   * Switch to a different database connection.
   * Pass url and alias so the handler can re-establish the connection in
   * kernels that don't have it yet (e.g. freshly opened notebooks).
   */
  async switchConnection(
    connectionKey: string,
    url?: string,
    alias?: string
  ): Promise<IConnectionResponse> {
    return this.post<IConnectionResponse>('switch', {
      connection_key: connectionKey,
      url: url ?? '',
      alias: alias ?? '',
    });
  }

  /**
   * Get list of running kernels
   */
  async getKernels(): Promise<IKernel[]> {
    const response = await this.get<{ kernels: IKernel[] }>('kernels');
    return response.kernels;
  }
}

/**
 * Singleton API instance
 */
let apiInstance: JupySQLAPI | null = null;

/**
 * Get the API client instance (singleton)
 */
export function getAPI(): JupySQLAPI {
  if (!apiInstance) {
    apiInstance = new JupySQLAPI();
  }
  return apiInstance;
}
