/** 入口：只装配（React DOM + Router + 全局重登状态）。 */
import React from 'react';
import ReactDOM from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { ReloginProvider } from './state/relogin';
import './index.css';

ReactDOM.createRoot(document.getElementById('root') as HTMLElement).render(
  <React.StrictMode>
    <BrowserRouter>
      <ReloginProvider>
        <App />
      </ReloginProvider>
    </BrowserRouter>
  </React.StrictMode>,
);
