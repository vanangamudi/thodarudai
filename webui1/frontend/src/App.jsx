import React, { useState, useEffect, useRef } from 'react'
import QueryForm from './QueryForm.jsx'
import './theme.css';

export default function App() {
  return (
    <div className="app-container">
      <h2 className="app-title">Tamil Splits Web UI</h2>
      <QueryForm />
    </div>
  )
}
