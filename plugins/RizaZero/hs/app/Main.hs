{-# LANGUAGE FlexibleContexts, OverloadedStrings, ExtendedDefaultRules #-}

module Main where

import App (renderPage)

main :: IO ()
main = putStrLn (show (renderPage ()))
